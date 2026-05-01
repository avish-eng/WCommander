from __future__ import annotations

import hashlib
from pathlib import Path

from multipane_commander.platform import app_data_dir


def _cache_dir() -> Path:
    d = app_data_dir() / "ai_summaries"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(path: Path) -> str | None:
    try:
        st = path.stat()
        raw = f"{path.resolve()}\n{st.st_mtime_ns}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]
    except OSError:
        return None


def load_summary(path: Path) -> str | None:
    k = _key(path)
    if k is None:
        return None
    try:
        return (_cache_dir() / f"{k}.txt").read_text(encoding="utf-8")
    except OSError:
        return None


def save_summary(path: Path, text: str) -> None:
    k = _key(path)
    if k is None:
        return
    try:
        (_cache_dir() / f"{k}.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass


def has_summary(path: Path) -> bool:
    k = _key(path)
    if k is None:
        return False
    return (_cache_dir() / f"{k}.txt").exists()
