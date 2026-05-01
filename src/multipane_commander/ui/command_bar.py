from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)


class OutputPanel(QFrame):
    dismissed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("commandBarOutput")
        self.setVisible(False)
        self.setMaximumHeight(150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._command_label = QLabel()
        self._command_label.setObjectName("commandBarOutputCommand")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("commandBarCloseButton")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.clicked.connect(self.clear)
        header.addWidget(self._command_label, 1)
        header.addWidget(close_btn)

        self._text = QLabel()
        self._text.setObjectName("commandBarOutputText")
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidget(self._text)
        scroll.setWidgetResizable(True)
        scroll.setFrameStyle(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        layout.addLayout(header)
        layout.addWidget(scroll, 1)

    def show_output(self, command: str, text: str) -> None:
        self._command_label.setText(f"$ {command}")
        self._text.setText(text.strip() or "(no output)")
        self.setVisible(True)

    def clear(self) -> None:
        self.setVisible(False)
        self._command_label.setText("")
        self._text.setText("")
        self.dismissed.emit()


class CommandBar(QFrame):
    navigate_requested = Signal(object)    # emits Path
    refresh_requested = Signal()
    escalate_requested = Signal(str, str)  # cwd, command

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("commandBar")

        self._cwd: Path = Path.home()
        self._history: list[str] = []
        self._history_index: int = -1
        self._process: QProcess | None = None
        self._pending_command: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.output_panel = OutputPanel(self)
        root.addWidget(self.output_panel)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(8, 4, 8, 4)
        input_row.setSpacing(4)

        self._prompt = QLabel(">")
        self._prompt.setObjectName("commandBarPrompt")
        self._prompt.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        self._input = QLineEdit()
        self._input.setObjectName("commandBarInput")
        self._input.setPlaceholderText("Enter command — Shift+Enter to run in terminal")
        self._input.installEventFilter(self)

        input_row.addWidget(self._prompt)
        input_row.addWidget(self._input, 1)

        input_widget = QWidget()
        input_widget.setObjectName("commandBarInputRow")
        input_widget.setLayout(input_row)
        root.addWidget(input_widget)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def set_cwd(self, path: Path) -> None:
        self._cwd = path
        name = path.name or str(path)
        self._prompt.setText(f"{name}>")
        self._prompt.setToolTip(str(path))

    def focus_input(self, initial_text: str = "") -> None:
        self._input.setFocus()
        if initial_text:
            current = self._input.text()
            if not current:
                self._input.setText(initial_text)
                self._input.end(False)

    # -------------------------------------------------------------------------
    # Event filter — keyboard handling inside the input field
    # -------------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            mods = event.modifiers()

            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self._escalate_to_terminal()
                else:
                    self._execute_inline()
                return True

            if key == Qt.Key.Key_Up:
                self._history_prev()
                return True

            if key == Qt.Key.Key_Down:
                self._history_next()
                return True

            if key == Qt.Key.Key_Escape:
                if self.output_panel.isVisible():
                    self.output_panel.clear()
                elif self._input.text():
                    self._input.clear()
                else:
                    self._input.clearFocus()
                return True

        return super().eventFilter(obj, event)

    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    def _execute_inline(self) -> None:
        command = self._input.text().strip()
        if not command:
            return

        self._add_to_history(command)
        self._input.clear()

        if self._is_cd_command(command):
            self._handle_cd(command)
            return

        log.debug("command_bar: inline %r in %s", command, self._cwd)

        if self._process is not None:
            self._process.kill()

        self._pending_command = command
        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(self._cwd))
        self._process.finished.connect(self._on_process_finished)

        if sys.platform == "win32":
            self._process.start("cmd.exe", ["/c", command])
        else:
            self._process.start("/bin/sh", ["-c", command])

    def _on_process_finished(self, exit_code: int, _exit_status) -> None:
        process = self._process
        self._process = None

        if process is None:
            return

        stdout = process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        stderr = process.readAllStandardError().data().decode("utf-8", errors="replace")
        process.deleteLater()

        log.debug("command_bar: exit code %d for %r", exit_code, self._pending_command)
        if stderr:
            log.warning("command_bar: stderr from %r: %s", self._pending_command, stderr.strip())

        output = stdout
        if stderr:
            output = (output + "\n" if output else "") + stderr
        self.output_panel.show_output(self._pending_command, output)
        self.refresh_requested.emit()

    def _escalate_to_terminal(self) -> None:
        command = self._input.text().strip()
        if not command:
            return
        self._add_to_history(command)
        self._input.clear()
        log.debug("command_bar: escalate %r in %s", command, self._cwd)
        self.escalate_requested.emit(str(self._cwd), command)

    # -------------------------------------------------------------------------
    # cd interception
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_cd_command(command: str) -> bool:
        parts = command.split()
        return bool(parts) and parts[0] == "cd"

    def _handle_cd(self, command: str) -> None:
        parts = command.split(None, 1)
        raw = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "~"

        if raw in ("~", ""):
            target = Path.home()
        elif os.path.isabs(raw):
            target = Path(raw)
        else:
            target = self._cwd / raw

        try:
            target = target.expanduser().resolve()
        except (OSError, RuntimeError):
            target = target.expanduser()

        log.debug("command_bar: cd → %s", target)

        if not target.exists() or not target.is_dir():
            log.warning("command_bar: cd target missing: %s", target)
            self.output_panel.show_output(command, f"cd: no such directory: {target}")
            return

        self.navigate_requested.emit(target)

    # -------------------------------------------------------------------------
    # History
    # -------------------------------------------------------------------------

    def _add_to_history(self, command: str) -> None:
        if not command:
            return
        if self._history and self._history[0] == command:
            self._history_index = -1
            return
        self._history.insert(0, command)
        self._history_index = -1

    def _history_prev(self) -> None:
        if not self._history:
            return
        self._history_index = min(self._history_index + 1, len(self._history) - 1)
        self._input.setText(self._history[self._history_index])
        self._input.end(False)

    def _history_next(self) -> None:
        if self._history_index <= 0:
            self._history_index = -1
            self._input.clear()
            return
        self._history_index -= 1
        self._input.setText(self._history[self._history_index])
        self._input.end(False)
