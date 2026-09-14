"""File search with incremental results and cooperative cancellation."""

from dataclasses import dataclass
from pathlib import Path
from threading import Event
import os
from fnmatch import fnmatchcase
from functools import lru_cache

MAX_RESULTS = 5_000
CONTENT_SIZE_LIMIT = 10 * 1024 * 1024


@dataclass(slots=True)
class FindResult:
    path: Path
    matched_content: bool


def find_files(
    root: Path,
    *,
    name_pattern="*",
    content_query="",
    recursive=True,
    max_results=MAX_RESULTS,
    cancelled: Event | None = None,
    on_batch=lambda batch: None,
) -> list[FindResult]:
    token = cancelled or Event()
    pattern = name_pattern or "*"
    if Path(pattern).is_absolute():
        raise ValueError("Use a relative glob pattern")
    pattern_parts = ("**", *Path(pattern).parts)
    if os.name == "nt":
        pattern_parts = tuple(part.lower() for part in pattern_parts)

    def matches(path):
        parts = path.relative_to(root).parts
        if os.name == "nt":
            parts = tuple(part.lower() for part in parts)

        @lru_cache(None)
        def match(index, pattern_index):
            if pattern_index == len(pattern_parts):
                return index == len(parts)
            component = pattern_parts[pattern_index]
            if component == "**":
                return match(index, pattern_index + 1) or (
                    index < len(parts) and match(index + 1, pattern_index)
                )
            return (
                index < len(parts)
                and fnmatchcase(parts[index], component)
                and match(index + 1, pattern_index + 1)
            )

        return match(0, 0)

    def candidates():
        if not recursive:
            yield from root.glob(pattern)
            return
        for directory, dirs, files in os.walk(root, followlinks=False):
            if token.is_set():
                return
            for name in files:
                if token.is_set():
                    return
                path = Path(directory) / name
                if matches(path):
                    yield path

    iterator = candidates()
    results, batch = [], []
    needle = content_query.lower()
    for candidate in iterator:
        if token.is_set() or len(results) >= max_results:
            break
        try:
            if not candidate.is_file():
                continue
            if needle:
                if candidate.stat().st_size > CONTENT_SIZE_LIMIT:
                    continue
                with candidate.open("rb") as handle:
                    chunks = []
                    for _ in range(10):
                        if token.is_set():
                            return results
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                data = b"".join(chunks)
                if (
                    b"\x00" in data[:8192]
                    or needle not in data.decode("utf-8", errors="replace").lower()
                ):
                    continue
        except OSError:
            continue
        result = FindResult(candidate, bool(needle))
        results.append(result)
        batch.append(result)
        if len(batch) >= 50:
            on_batch(batch)
            batch = []
    if batch:
        on_batch(batch)
    return results
