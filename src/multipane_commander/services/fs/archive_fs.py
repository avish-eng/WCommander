"""Read-only virtual filesystem for browsing into zip / tar / 7z / rar / jar.

Virtual-path encoding: an entry inside `/abs/foo.zip` is encoded as
`Path("/abs/foo.zip/inner/file.txt")`. Because `/abs/foo.zip` is a real file,
a real path with the same prefix can never exist on disk — so the encoding
collision-free, and pathlib's `.parent` / `.name` semantics give us correct
breadcrumb behaviour for free.
"""

from __future__ import annotations

import tempfile
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath

from multipane_commander.domain.entries import EntryInfo
from multipane_commander.services.fs.local_fs import LocalFileSystem, OperationCancelled


_ARCHIVE_SUFFIXES = {".zip", ".tar", ".7z", ".rar", ".jar"}
_ARCHIVE_COMPOUND_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz")


def is_archive_file(path: Path) -> bool:
    """True iff ``path`` is a real on-disk file with a recognised archive suffix."""
    if not path.exists() or not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix in _ARCHIVE_SUFFIXES:
        return True
    name = path.name.lower()
    return any(name.endswith(compound) for compound in _ARCHIVE_COMPOUND_SUFFIXES)


def find_archive_root(path: Path) -> Path | None:
    """Walk up ``path``'s ancestors looking for an archive file.

    Returns the archive's real on-disk path, or None if ``path`` isn't
    inside (or is) an archive.
    """
    current = path
    while True:
        if is_archive_file(current):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def inside_archive(path: Path) -> tuple[Path, PurePosixPath] | None:
    """If ``path`` is inside (or is) an archive, return (root, inner_path).

    ``inner_path`` is "" for the archive root itself, and a posix-style
    path for entries inside.
    """
    root = find_archive_root(path)
    if root is None:
        return None
    if path == root:
        return root, PurePosixPath("")
    # `path` is a descendant of root → strip the prefix.
    relative = path.relative_to(root)
    return root, PurePosixPath(*relative.parts)


def virtual_path(archive_root: Path, inner: PurePosixPath | str) -> Path:
    """Build the encoded path for an entry inside ``archive_root``."""
    inner_str = str(inner) if inner else ""
    if not inner_str or inner_str == ".":
        return archive_root
    return archive_root / inner_str


class ArchiveReadError(RuntimeError):
    """Raised when libarchive can't open or read the archive."""


class ArchiveEntryNotFound(KeyError):
    """Raised when an inner path doesn't exist in the archive."""


class ArchiveFileSystem:
    """Read-only filesystem for entries inside an archive.

    The interface mirrors the read-side of LocalFileSystem so PaneView can
    swap implementations without conditionals at every call site.
    """

    def __init__(self, *, check_cancel: Callable[[], None] = lambda: None,
                 on_bytes: Callable[[int], None] = lambda count: None) -> None:
        self.check_cancel = check_cancel
        self.on_bytes = on_bytes

    def list_dir(self, path: Path) -> list[EntryInfo]:
        ctx = inside_archive(path)
        if ctx is None:
            raise ArchiveReadError(f"{path} is not inside an archive")
        archive_root, inner = ctx
        return _list_archive_dir(archive_root, inner, check_cancel=self.check_cancel)

    def extract_entry_to(self, path: Path, destination: Path) -> None:
        """Extract the archive entry at ``path`` to a real file ``destination``."""
        ctx = inside_archive(path)
        if ctx is None:
            raise ArchiveReadError(f"{path} is not inside an archive")
        archive_root, inner = ctx
        if not str(inner) or str(inner) == ".":
            raise ArchiveReadError("Cannot extract the archive root itself")
        fs = LocalFileSystem()
        staged = fs._temporary_sibling(destination)
        try:
            _extract_one(archive_root, inner, staged,
                         check_cancel=self.check_cancel, on_bytes=self.on_bytes)
            self.check_cancel()
            fs.replace_entry(staged, destination, operation="move")
        finally:
            if os.path.lexists(staged):
                fs.remove_existing(staged)

    def extract_entry_to_temp(self, path: Path) -> Path:
        """Extract ``path`` to a fresh temp file; caller is responsible for cleanup."""
        ctx = inside_archive(path)
        if ctx is None:
            raise ArchiveReadError(f"{path} is not inside an archive")
        archive_root, inner = ctx
        if not str(inner) or str(inner) == ".":
            raise ArchiveReadError("Cannot extract the archive root itself")
        # Preserve the file's extension so QuickView can dispatch correctly.
        suffix = Path(str(inner)).suffix
        fd, tmp_path = tempfile.mkstemp(prefix="mpc-archive-", suffix=suffix)
        # mkstemp returns an open fd; close it so we can write via pathlib.
        import os

        os.close(fd)
        try:
            _extract_one(archive_root, inner, Path(tmp_path))
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
        return Path(tmp_path)


def _list_archive_dir(archive_root: Path, inner: PurePosixPath, *,
                      check_cancel: Callable[[], None] = lambda: None) -> list[EntryInfo]:
    """Return the entries directly under ``inner`` inside ``archive_root``."""
    import libarchive

    inner_str = str(inner) if str(inner) != "." else ""
    prefix = (inner_str + "/") if inner_str else ""

    # libarchive may emit the same logical directory multiple times (once
    # implicit per file, once as an explicit dir entry). We dedupe by name.
    direct_children: dict[str, EntryInfo] = {}

    try:
        with libarchive.file_reader(str(archive_root)) as reader:
            for entry in reader:
                check_cancel()
                pathname = entry.pathname
                if not pathname:
                    continue
                # Normalise: strip leading "./", strip trailing "/".
                normalised = str(_safe_member(pathname))
                is_dir_entry = entry.isdir
                if normalised in {"", "."}:
                    continue
                if prefix:
                    if not normalised.startswith(prefix):
                        continue
                    rest = normalised[len(prefix):]
                else:
                    rest = normalised
                if "/" in rest:
                    # Indirect descendant — record the first segment as a dir.
                    first = rest.split("/", 1)[0]
                    if first not in direct_children:
                        direct_children[first] = EntryInfo(
                            name=first,
                            path=virtual_path(archive_root, prefix + first),
                            is_dir=True,
                            size=0,
                            extension="",
                            modified_at=datetime.fromtimestamp(0),
                        )
                    continue
                # Direct child.
                size = 0 if is_dir_entry else (getattr(entry, "size", 0) or 0)
                mtime = getattr(entry, "mtime", 0) or 0
                try:
                    modified = datetime.fromtimestamp(mtime)
                except (ValueError, OSError, OverflowError):
                    modified = datetime.fromtimestamp(0)
                direct_children[rest] = EntryInfo(
                    name=rest,
                    path=virtual_path(archive_root, prefix + rest),
                    is_dir=is_dir_entry,
                    size=size,
                    extension="" if is_dir_entry else Path(rest).suffix.lstrip(".").upper(),
                    modified_at=modified,
                )
    except OperationCancelled:
        raise
    except Exception as exc:  # libarchive raises ArchiveError, OSError, etc.
        raise ArchiveReadError(f"Failed to read {archive_root}: {exc}") from exc

    return sorted(
        direct_children.values(),
        key=lambda entry: (not entry.is_dir, entry.name.lower()),
    )


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts):
        raise ArchiveReadError(f"Unsafe archive member: {name}")
    return path


def _extract_one(archive_root: Path, inner: PurePosixPath, destination: Path, *,
                 check_cancel: Callable[[], None] = lambda: None,
                 on_bytes: Callable[[int], None] = lambda count: None) -> None:
    """Extract a file or subtree, including archives with implicit directories."""
    import libarchive

    target = _safe_member(str(inner))
    found = False
    try:
        with libarchive.file_reader(str(archive_root)) as reader:
            for entry in reader:
                check_cancel()
                member = _safe_member(entry.pathname or "")
                if member != target and not member.is_relative_to(target):
                    continue
                found = True
                if entry.issym or entry.islnk or not (entry.isfile or entry.isdir):
                    raise ArchiveReadError(f"Unsupported archive link or special file: {member}")
                relative = member.relative_to(target)
                output = destination.joinpath(*relative.parts)
                if not output.resolve().is_relative_to(destination.resolve()):
                    raise ArchiveReadError(f"Unsafe extraction destination: {member}")
                if entry.isdir:
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("wb") as out:
                    for block in entry.get_blocks():
                        check_cancel()
                        out.write(block)
                        on_bytes(len(block))
    except (OperationCancelled, ArchiveReadError):
        raise
    except Exception as exc:
        raise ArchiveReadError(f"Failed to read {archive_root}: {exc}") from exc
    if not found:
        raise ArchiveEntryNotFound(f"{inner} not found in {archive_root}")


__all__ = [
    "ArchiveFileSystem",
    "ArchiveReadError",
    "ArchiveEntryNotFound",
    "find_archive_root",
    "inside_archive",
    "is_archive_file",
    "virtual_path",
]
