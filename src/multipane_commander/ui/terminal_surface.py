from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFocusEvent, QFont, QFontDatabase, QKeyEvent, QKeySequence, QPainter, QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from multipane_commander.terminal.ansi import TerminalBuffer


class TerminalSurface(QPlainTextEdit):
    command_submitted = Signal(str)
    terminal_resized = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("terminalOutput")
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed_font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setFont(fixed_font)
        self._draft = ""
        self._local_echo = False
        self._submit_sequence = b"\r"
        self._sender = lambda _data: None
        self._buffer = TerminalBuffer()
        self._last_local_command = ""
        self._input_ready = True
        self._pending_bytes: list[bytes] = []
        self._terminal_cursor_focused = False
        self.setTabStopDistance(self._cell_size().width() * 8)
        self.selectionChanged.connect(self.viewport().update)

    def set_sender(self, sender) -> None:
        self._sender = sender

    def set_local_echo(self, enabled: bool) -> None:
        self._local_echo = enabled

    def set_submit_sequence(self, submit_sequence: bytes) -> None:
        self._submit_sequence = submit_sequence or b"\r"

    def set_input_ready(self, ready: bool) -> None:
        self._input_ready = ready
        if not ready:
            return
        if not self._pending_bytes:
            return
        pending = self._pending_bytes
        self._pending_bytes = []
        for chunk in pending:
            self._sender(chunk)

    def input_ready(self) -> bool:
        return self._input_ready

    def append_output(self, text: str) -> None:
        if self._local_echo:
            text = self._normalize_local_echo_output(text)
            if not text:
                return
        rendered = self._buffer.feed(text)
        self.setPlainText(rendered)
        self._sync_text_cursor_to_terminal_cursor()
        self.ensureCursorVisible()
        self.viewport().update()

    def inject_command(self, command: str, *, run: bool) -> None:
        if not command:
            return
        if self._local_echo:
            self.append_output(command)
            self._last_local_command = command.strip()
        else:
            self._send_text(command)
        self._draft = command
        if run:
            self._submit_current_command()

    def current_draft(self) -> str:
        return self._draft

    def clear_draft(self) -> None:
        self._draft = ""

    def clear(self) -> None:  # type: ignore[override]
        self._buffer.clear()
        self._last_local_command = ""
        self._pending_bytes = []
        super().clear()
        self._sync_text_cursor_to_terminal_cursor()
        self.viewport().update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        cols, rows = self._grid_size()
        if cols > 0 and rows > 0:
            self._buffer.set_size(cols, rows)
            self.terminal_resized.emit(cols, rows)
        self.viewport().update()

    def focusInEvent(self, event: QFocusEvent) -> None:  # type: ignore[override]
        super().focusInEvent(event)
        self._terminal_cursor_focused = True
        self._sync_text_cursor_to_terminal_cursor()
        self.viewport().update()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # type: ignore[override]
        super().focusOutEvent(event)
        self._terminal_cursor_focused = False
        self.viewport().update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self._should_draw_terminal_cursor():
            return

        cursor_rect = self.cursorRect(self.textCursor())
        cell = self._cell_size()
        width = max(2, cell.width())
        height = max(2, min(cell.height(), cursor_rect.height() or cell.height()))
        x = min(max(0, cursor_rect.x()), max(0, self.viewport().width() - width))
        y = min(max(0, cursor_rect.y()), max(0, self.viewport().height() - height))
        color = self.palette().highlight().color()
        if not color.isValid():
            color = QColor("#4FD1FF")
        painter = QPainter(self.viewport())
        painter.fillRect(x, y, width, height, color)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            text = QApplication.clipboard().text()
            if text:
                if self._local_echo:
                    self.append_output(text)
                else:
                    self._send_text(text)
                self._draft += text
            return
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            control_payload = self._control_sequence(event.key())
            if control_payload is not None:
                self._send_bytes(control_payload)
                if event.key() in {Qt.Key.Key_C, Qt.Key.Key_D, Qt.Key.Key_Z, Qt.Key.Key_Q}:
                    self.clear_draft()
                return

        key = event.key()
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._submit_current_command()
            return
        if key == Qt.Key.Key_Backspace:
            if self._local_echo:
                if self._draft:
                    self._draft = self._draft[:-1]
                    self._erase_last_visible_character()
            else:
                self._send_bytes(b"\x08")
            return
        if key == Qt.Key.Key_Tab:
            if self._local_echo:
                self.append_output("\t")
            else:
                self._send_bytes(b"\t")
            self._draft += "\t"
            return

        navigation = self._navigation_sequence(key)
        if navigation is not None:
            if not self._local_echo:
                self._send_text(navigation)
            return

        text = event.text()
        if text:
            if text not in {"\r", "\n"}:
                if self._local_echo:
                    self.append_output(text)
                else:
                    self._send_text(text)
                self._draft += text
            return

        super().keyPressEvent(event)

    def focusNextPrevChild(self, _next: bool) -> bool:  # type: ignore[override]
        return False

    def _submit_current_command(self) -> None:
        command = self._draft.strip()
        if self._local_echo and self._is_local_clear_command(command):
            self.clear()
            if command:
                self.command_submitted.emit(command)
            self.clear_draft()
            return

        if self._local_echo:
            if self._draft:
                self._send_text(self._draft)
            self._send_bytes(self._submit_sequence)
        else:
            self._send_bytes(self._submit_sequence)
        if self._local_echo:
            self.append_output("\n")
        if command:
            self.command_submitted.emit(command)
        self.clear_draft()

    def _send_text(self, text: str) -> None:
        self._send_bytes(text.encode("utf-8", errors="replace"))

    def _send_bytes(self, data: bytes) -> None:
        if not self._input_ready:
            self._pending_bytes.append(data)
            return
        self._sender(data)

    def _erase_last_visible_character(self) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.deletePreviousChar()
        self.setTextCursor(cursor)
        self.viewport().update()

    def _sync_text_cursor_to_terminal_cursor(self) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self._document_position_for_terminal_cursor())
        self.setTextCursor(cursor)

    def _document_position_for_terminal_cursor(self) -> int:
        text = self.toPlainText()
        if not text:
            return 0

        lines = text.split("\n")
        if self._buffer.cursor_row >= len(lines):
            return len(text)

        row = max(0, self._buffer.cursor_row)
        position = sum(len(line) + 1 for line in lines[:row])
        column = min(max(0, self._buffer.cursor_col), len(lines[row]))
        return position + column

    def _should_draw_terminal_cursor(self) -> bool:
        return self._terminal_cursor_focused and not self.textCursor().hasSelection()

    def _normalize_local_echo_output(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n")
        if self._last_local_command:
            command_echo = self._last_local_command + "\n"
            if normalized.startswith(command_echo):
                normalized = normalized[len(command_echo) :]
            elif normalized == self._last_local_command:
                normalized = ""
        while "\n\n\n" in normalized:
            normalized = normalized.replace("\n\n\n", "\n\n")
        if normalized and normalized != "\n":
            self._last_local_command = ""
        return normalized

    @staticmethod
    def _is_local_clear_command(command: str) -> bool:
        return command.casefold() in {"cls", "clear"}

    def _grid_size(self) -> tuple[int, int]:
        viewport = self.viewport().size()
        cell = self._cell_size()
        if cell.width() <= 0 or cell.height() <= 0:
            return (0, 0)
        cols = max(1, viewport.width() // cell.width())
        rows = max(1, viewport.height() // cell.height())
        return (cols, rows)

    def _cell_size(self) -> QSize:
        metrics = self.fontMetrics()
        width = max(1, metrics.horizontalAdvance("M"))
        height = max(1, metrics.lineSpacing())
        return QSize(width, height)

    @staticmethod
    def _control_sequence(key: int) -> bytes | None:
        mapping = {
            Qt.Key.Key_A: b"\x01",
            Qt.Key.Key_B: b"\x02",
            Qt.Key.Key_C: b"\x03",
            Qt.Key.Key_D: b"\x04",
            Qt.Key.Key_E: b"\x05",
            Qt.Key.Key_F: b"\x06",
            Qt.Key.Key_K: b"\x0b",
            Qt.Key.Key_L: b"\x0c",
            Qt.Key.Key_N: b"\x0e",
            Qt.Key.Key_P: b"\x10",
            Qt.Key.Key_Q: b"\x11",
            Qt.Key.Key_U: b"\x15",
            Qt.Key.Key_W: b"\x17",
            Qt.Key.Key_Z: b"\x1a",
        }
        return mapping.get(key)

    @staticmethod
    def _navigation_sequence(key: int) -> str | None:
        mapping = {
            Qt.Key.Key_Left: "\x1b[D",
            Qt.Key.Key_Right: "\x1b[C",
            Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B",
            Qt.Key.Key_Home: "\x1b[H",
            Qt.Key.Key_End: "\x1b[F",
            Qt.Key.Key_Delete: "\x1b[3~",
            Qt.Key.Key_PageUp: "\x1b[5~",
            Qt.Key.Key_PageDown: "\x1b[6~",
            Qt.Key.Key_Escape: "\x1b",
        }
        return mapping.get(key)
