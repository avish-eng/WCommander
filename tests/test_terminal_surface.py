from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from multipane_commander.ui.terminal_surface import TerminalSurface


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def _ctrl_c_event() -> QKeyEvent:
    return QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_C,
        Qt.KeyboardModifier.ControlModifier,
        "\x03",
    )


def test_terminal_surface_ctrl_c_without_selection_is_copy_only_noop() -> None:
    _qapp()
    surface = TerminalSurface()
    sent: list[bytes] = []
    surface.set_sender(sent.append)
    surface.set_input_ready(False)

    surface.keyPressEvent(_ctrl_c_event())

    assert sent == []
    assert surface._pending_bytes == []


def test_terminal_surface_ctrl_c_with_selection_copies_text() -> None:
    app = _qapp()
    surface = TerminalSurface()
    app.clipboard().clear()
    surface.append_output("hello")
    surface.selectAll()

    surface.keyPressEvent(_ctrl_c_event())

    assert app.clipboard().text() == "hello"
