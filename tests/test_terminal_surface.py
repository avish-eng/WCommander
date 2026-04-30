from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent
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


def test_terminal_surface_draws_cursor_while_focused_without_selection() -> None:
    _qapp()
    surface = TerminalSurface()

    surface.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.OtherFocusReason))

    assert surface._should_draw_terminal_cursor() is True

    surface.append_output("hello")
    surface.selectAll()

    assert surface._should_draw_terminal_cursor() is False

    surface.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.OtherFocusReason))

    assert surface._should_draw_terminal_cursor() is False


def test_terminal_surface_syncs_caret_to_terminal_buffer_cursor() -> None:
    _qapp()
    surface = TerminalSurface()

    surface.append_output("abc\rX")

    assert surface.toPlainText() == "Xbc"
    assert surface.textCursor().position() == 1
