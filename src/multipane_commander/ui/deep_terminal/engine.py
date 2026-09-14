from __future__ import annotations

import logging

from multipane_commander.ui.deep_terminal.dock import DeepTerminalDock
from multipane_commander.ui.deep_terminal.surface import WEB_TERMINAL_AVAILABLE
from multipane_commander.ui.terminal_dock import TerminalDock

log = logging.getLogger(__name__)

ENGINE_DEEP = "deep"
ENGINE_CLASSIC = "classic"
_ENGINES = {ENGINE_DEEP, ENGINE_CLASSIC}


def normalize_engine(engine: str | None) -> str:
    if engine in _ENGINES:
        return engine
    return ENGINE_DEEP


def deep_terminal_available() -> bool:
    return WEB_TERMINAL_AVAILABLE


def resolve_engine(engine: str | None) -> str:
    normalized = normalize_engine(engine)
    if normalized == ENGINE_DEEP and not deep_terminal_available():
        return ENGINE_CLASSIC
    return normalized


def create_terminal_dock(*, engine: str | None = None, **kwargs):
    resolved = resolve_engine(engine)
    if resolved == ENGINE_DEEP:
        try:
            return DeepTerminalDock(**kwargs)
        except Exception:
            log.exception("Deep terminal failed to initialise; falling back to classic")
    return TerminalDock(**kwargs)
