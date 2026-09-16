"""Lazy exports allow both terminal modes to share the same renderer."""
from importlib import import_module

_MODULES = {
    "DeepTerminalDock": "dock", "ENGINE_CLASSIC": "engine", "ENGINE_DEEP": "engine",
    "create_terminal_dock": "engine", "deep_terminal_available": "engine",
    "normalize_engine": "engine", "resolve_engine": "engine",
    "DeepTerminalSurface": "surface", "WEB_TERMINAL_AVAILABLE": "surface",
    "build_deep_terminal_html": "surface", "create_deep_surface": "surface",
}
__all__ = list(_MODULES)


def __getattr__(name):
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value
