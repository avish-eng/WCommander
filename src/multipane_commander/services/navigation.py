"""Tab history and typed path resolution without widget dependencies."""

import os
from pathlib import Path


def ensure_history(tab):
    if not tab.navigation_history:
        tab.navigation_history = [tab.path]
        tab.navigation_index = 0
    tab.navigation_index = max(0, min(tab.navigation_index, len(tab.navigation_history) - 1))


def record_navigation(tab, path):
    ensure_history(tab)
    tab.navigation_history = tab.navigation_history[: tab.navigation_index + 1]
    if tab.navigation_history[-1] != path:
        tab.navigation_history.append(path)
    tab.navigation_index = len(tab.navigation_history) - 1


def resolve_typed_path(raw: str, current: Path) -> Path | None:
    cleaned = raw.strip().strip('"')
    if not cleaned:
        return None
    candidate = Path(os.path.expandvars(os.path.expanduser(cleaned)))
    if not candidate.is_absolute():
        candidate = current / candidate
    try:
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved
        if resolved.is_file():
            return resolved.parent
    except OSError:
        pass
    return None
