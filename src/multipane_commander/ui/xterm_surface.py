"""Compatibility names for the shared, bundled xterm renderer."""
from PySide6.QtWidgets import QWidget
from multipane_commander.terminal.deep.input_tracker import update_draft_from_input
from multipane_commander.ui.deep_terminal.surface import (
    WEB_TERMINAL_AVAILABLE,
    DeepTerminalBridge as XtermBridge,
    DeepTerminalSurface as XtermTerminalSurface,
    build_deep_terminal_html as build_xterm_html,
)
from multipane_commander.ui.terminal_surface import TerminalSurface

__all__ = ["WEB_TERMINAL_AVAILABLE", "XtermBridge", "XtermTerminalSurface",
           "build_xterm_html", "create_terminal_surface", "update_draft_from_input"]


def create_terminal_surface(parent: QWidget | None = None):
    if WEB_TERMINAL_AVAILABLE:
        return XtermTerminalSurface(parent)
    return TerminalSurface(parent)
