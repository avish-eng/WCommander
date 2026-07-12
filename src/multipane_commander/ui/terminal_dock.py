from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import Property, QEvent, QPoint, QTime, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
)

from multipane_commander.terminal.session import TerminalSession
from multipane_commander.ui.xterm_surface import WEB_TERMINAL_AVAILABLE, create_terminal_surface


_PINNED_COMMAND_ROLE = Qt.ItemDataRole.UserRole


class _CommandHistoryList(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self._pinned_text_color = QColor("#D8A144")

    def _get_pinned_text_color(self) -> QColor:
        return self._pinned_text_color

    def _set_pinned_text_color(self, color: QColor) -> None:
        self._pinned_text_color = QColor(color)
        self.viewport().update()

    pinnedTextColor = Property(
        QColor,
        _get_pinned_text_color,
        _set_pinned_text_color,
    )


class _CommandHistoryDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        pinned = bool(index.data(_PINNED_COMMAND_ROLE))
        paint_option = QStyleOptionViewItem(option)
        if pinned:
            accent = option.palette.highlight().color()
            tint = QColor(accent)
            tint.setAlpha(24)
            painter.fillRect(option.rect, tint)
            history_list = self.parent()
            if isinstance(history_list, _CommandHistoryList):
                pinned_text = history_list._get_pinned_text_color()
                paint_option.palette.setColor(QPalette.ColorRole.Text, pinned_text)
                paint_option.palette.setColor(
                    QPalette.ColorRole.HighlightedText,
                    pinned_text,
                )

        super().paint(painter, paint_option, index)

        if pinned:
            painter.fillRect(option.rect.x(), option.rect.y(), 2, option.rect.height(), accent)


class TerminalDock(QFrame):
    maximize_requested = Signal()
    follow_active_pane_toggled = Signal(bool)
    commands_changed = Signal(object, object)
    history_panel_visibility_changed = Signal(bool)
    experimental_pty_toggled = Signal(bool)

    def __init__(
        self,
        *,
        initial_directory: Path,
        visible: bool,
        follow_active_pane: bool,
        experimental_pty: bool = False,
        recent_commands: list[str] | None = None,
        bookmarked_commands: list[str] | None = None,
        history_panel_visible: bool = False,
    ) -> None:
        super().__init__()
        self.setObjectName("terminalDock")
        self.setVisible(visible)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._is_maximized = False
        self._side_by_side_mode = False
        self._follow_active_pane = follow_active_pane
        self._current_directory = initial_directory
        # A real PTY is the natural backend for xterm. Keep the old setting as
        # an escape hatch, but prefer PTY automatically for the new surface.
        self._experimental_pty = experimental_pty or WEB_TERMINAL_AVAILABLE
        self._recent_commands = self._unique_commands(recent_commands or [])
        self._bookmarked_commands = self._unique_commands(bookmarked_commands or [])
        self._output_press_pos: QPoint | None = None
        self._output_dragged = False
        self._pty_ready_timer = QTimer(self)
        self._pty_ready_timer.setSingleShot(True)
        self._pty_ready_timer.setInterval(150)
        self._pty_ready_timer.timeout.connect(self._release_pty_input)
        self.session = self._build_session(initial_directory)
        self.output = create_terminal_surface()
        self.output.command_submitted.connect(self._remember_command)
        self.output.terminal_resized.connect(self._resize_active_session)
        self.runtime_label = QLabel(self._runtime_description())
        self.backend_status_label = QLabel()
        self.follow_button = QPushButton()
        self.maximize_button = QPushButton("Expand")
        self.history_button = QPushButton("History")
        self.more_button = QPushButton("⋯")
        self.action_status_label = QLabel()
        self._action_status_timer = QTimer(self)
        self._action_status_timer.setSingleShot(True)
        self._action_status_timer.setInterval(6000)
        self._action_status_timer.timeout.connect(self.action_status_label.hide)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 8, 9, 9)
        layout.setSpacing(6)

        header_top = QHBoxLayout()
        header_top.setSpacing(6)
        title = QLabel("Terminal")
        title.setObjectName("terminalTitle")
        self.runtime_label.setObjectName("terminalRuntime")
        self.runtime_label.setWordWrap(False)
        self.runtime_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.runtime_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.backend_status_label.setObjectName("terminalBackendStatus")
        self.follow_button.setObjectName("terminalToggleButton")
        self.follow_button.setCheckable(True)
        self.follow_button.clicked.connect(self._toggle_follow_active_pane)
        self.maximize_button.setObjectName("terminalCompactButton")
        self.maximize_button.clicked.connect(self.maximize_requested.emit)
        self.history_button.setObjectName("terminalToggleButton")
        self.history_button.setCheckable(True)
        self.history_button.clicked.connect(self._toggle_history_panel)
        self.more_button.setObjectName("terminalMoreButton")
        self.more_button.setToolTip("More terminal actions")
        self.more_menu = QMenu(self)
        self.more_menu.setObjectName("contextMenu")
        self.clear_action = self.more_menu.addAction("Clear terminal")
        self.clear_action.triggered.connect(lambda _checked=False: self.output.clear())
        self.rerun_action = self.more_menu.addAction("Rerun last command")
        self.rerun_action.triggered.connect(lambda _checked=False: self._rerun_last_command())
        self.kill_action = self.more_menu.addAction("Kill current process")
        self.kill_action.setToolTip("Force stop the current process and restart the shell (Ctrl+Shift+K)")
        self.kill_action.triggered.connect(
            lambda _checked=False: self._force_kill_current_program()
        )
        self.more_menu.addSeparator()
        self.pty_action = self.more_menu.addAction("Use PTY backend")
        self.pty_action.setCheckable(True)
        self.pty_action.triggered.connect(self._toggle_experimental_pty)
        self.restart_action = self.more_menu.addAction("Restart shell")
        self.restart_action.triggered.connect(lambda _checked=False: self.restart_shell())
        self.more_button.setMenu(self.more_menu)
        self.action_status_label.setObjectName("terminalActionStatus")
        self.action_status_label.setVisible(False)

        header_top.addWidget(title)
        header_top.addWidget(self.runtime_label, 1)
        header_top.addWidget(self.backend_status_label)
        header_top.addWidget(self.action_status_label)
        header_top.addWidget(self.history_button)
        header_top.addWidget(self.follow_button)
        header_top.addWidget(self.maximize_button)
        header_top.addWidget(self.more_button)

        self.output.viewport().installEventFilter(self)

        terminal_surface = QFrame()
        terminal_surface.setObjectName("terminalSurface")
        terminal_surface_layout = QVBoxLayout(terminal_surface)
        terminal_surface_layout.setContentsMargins(0, 0, 0, 0)
        terminal_surface_layout.setSpacing(0)
        terminal_surface_layout.addWidget(self.output, 1)

        self.command_list = _CommandHistoryList()
        self.command_list.setObjectName("terminalCommandList")
        self.command_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.command_list.setSpacing(1)
        self.command_list.setUniformItemSizes(True)
        self.command_list.setItemDelegate(_CommandHistoryDelegate(self.command_list))
        self.command_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.command_list.customContextMenuRequested.connect(self._show_command_context_menu)
        self.command_list.installEventFilter(self)
        self.command_list.itemDoubleClicked.connect(self._run_clicked_command)

        history_panel = QFrame()
        history_panel.setObjectName("terminalHistoryPanel")
        history_panel.setMinimumWidth(260)
        history_layout = QVBoxLayout(history_panel)
        history_layout.setContentsMargins(5, 5, 5, 5)
        history_layout.setSpacing(0)
        history_layout.addWidget(self.command_list, 1)
        self.history_panel = history_panel

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(terminal_surface)
        self.content_splitter.addWidget(self.history_panel)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([980, 320])

        layout.addLayout(header_top)
        layout.addWidget(self.content_splitter, 1)

        self._bind_session()
        self.set_follow_active_pane(follow_active_pane)
        self.set_experimental_pty(self._experimental_pty, emit=False)
        self.set_history_panel_visible(history_panel_visible, emit=False)
        self._refresh_command_lists()
        self._update_rerun_button()
        if visible:
            self._ensure_session_started()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        command_list = getattr(self, "command_list", None)

        if watched is self.output.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                self._output_press_pos = event.position().toPoint()
                self._output_dragged = False
            elif event.type() == QEvent.Type.MouseMove and self._output_press_pos is not None:
                if (
                    event.position().toPoint() - self._output_press_pos
                ).manhattanLength() > QApplication.startDragDistance():
                    self._output_dragged = True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if not self._output_dragged:
                    self.focus_input()
                self._output_press_pos = None
                self._output_dragged = False
        elif watched is command_list and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
                self._run_selected_command()
                return True
            if (
                event.key() == Qt.Key.Key_Delete
                and not event.modifiers()
                and self._selected_command_is_pinned()
            ):
                self._remove_selected_bookmark()
                return True
            if event.key() == Qt.Key.Key_Escape and not event.modifiers():
                self.focus_input()
                return True
        return super().eventFilter(watched, event)

    def focus_input(self) -> None:
        self.output.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())
        if self.isVisible():
            self._ensure_session_started()
            self.focus_input()

    def inject_command(self, cwd: str, command: str) -> None:
        """Navigate PTY to cwd and run command. Starts session if not running."""
        path = Path(cwd)
        self._current_directory = path
        if not self._ensure_session_started():
            self.setVisible(True)
            self.focus_input()
            return
        self.session.change_directory(path)
        self._run_command(command)
        if not self.isVisible():
            self.setVisible(True)
            self.focus_input()

    def set_maximized(self, maximized: bool) -> None:
        self._is_maximized = maximized
        self.maximize_button.setText("Restore" if maximized else "Expand")
        self.setMinimumHeight(0 if maximized or self._side_by_side_mode else 220)
        vertical_policy = (
            QSizePolicy.Policy.Expanding
            if maximized or self._side_by_side_mode
            else QSizePolicy.Policy.Fixed
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, vertical_policy)

    def set_side_by_side_mode(self, enabled: bool) -> None:
        self._side_by_side_mode = enabled
        self.setMinimumHeight(0 if enabled or self._is_maximized else 220)
        vertical_policy = (
            QSizePolicy.Policy.Expanding
            if enabled or self._is_maximized
            else QSizePolicy.Policy.Fixed
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, vertical_policy)

    def sync_to_path(self, path: Path, *, enabled: bool) -> None:
        self.set_follow_active_pane(enabled)
        if enabled:
            self._current_directory = path
            self.session.change_directory(path)

    def set_follow_active_pane(self, enabled: bool) -> None:
        self._follow_active_pane = enabled
        self.follow_button.blockSignals(True)
        self.follow_button.setChecked(enabled)
        self.follow_button.blockSignals(False)
        self.follow_button.setText("Follow pane" if enabled else "Independent")
        self.follow_button.setToolTip(
            "Terminal follows the active file pane"
            if enabled
            else "Terminal keeps its own working directory"
        )
        self.follow_button.setProperty("active", enabled)
        self.follow_button.style().unpolish(self.follow_button)
        self.follow_button.style().polish(self.follow_button)

    def set_history_panel_visible(self, visible: bool, *, emit: bool = True) -> None:
        self.history_panel.setVisible(visible)
        self.history_button.blockSignals(True)
        self.history_button.setChecked(visible)
        self.history_button.blockSignals(False)
        self.history_button.setProperty("active", visible)
        self.history_button.style().unpolish(self.history_button)
        self.history_button.style().polish(self.history_button)
        if emit:
            self.history_panel_visibility_changed.emit(visible)

    def restart_shell(self) -> None:
        self.session.stop()
        self.output.clear()
        self.session.start()

    def close_session(self) -> None:
        self.session.stop()

    def set_experimental_pty(self, enabled: bool, *, emit: bool = True) -> None:
        self._experimental_pty = enabled
        self.pty_action.blockSignals(True)
        self.pty_action.setChecked(enabled)
        self.pty_action.blockSignals(False)
        self._refresh_backend_ui()
        if emit:
            self.experimental_pty_toggled.emit(enabled)

    def recent_commands(self) -> list[str]:
        return list(self._recent_commands)

    def bookmarked_commands(self) -> list[str]:
        return list(self._bookmarked_commands)

    def copy_selected_text(self) -> None:
        self.output.copy()

    def cut_selected_text(self) -> None:
        return

    def force_kill_current_program(self) -> None:
        self._force_kill_current_program()

    def paste_to_input(self) -> None:
        self.focus_input()
        paste_from_clipboard = getattr(self.output, "paste_from_clipboard", None)
        if callable(paste_from_clipboard):
            paste_from_clipboard()
            return
        text = QApplication.clipboard().text()
        if text:
            self.output.inject_command(text, run=False)

    def _append_output(self, text: str) -> None:
        self.output.append_output(text)
        if self.output.input_ready():
            return
        if self._looks_ready_for_input():
            self._pty_ready_timer.start()

    def _handle_started(self) -> None:
        self.runtime_label.setText(self._runtime_description())
        self._refresh_backend_ui()

    def _runtime_description(self) -> str:
        frontend = (
            "xterm.js"
            if bool(getattr(self.output, "accepts_immediate_input", False))
            else "Qt text fallback"
        )
        shell = {
            "pwsh": "PowerShell 7",
            "powershell": "Windows PowerShell",
            "cmd": "Command Prompt",
            "posix": "POSIX shell",
        }.get(self.session.shell_kind, self.session.shell_kind)
        return f"{frontend} · {shell}"

    def _toggle_follow_active_pane(self, enabled: bool) -> None:
        self.set_follow_active_pane(enabled)
        self.follow_active_pane_toggled.emit(enabled)

    def _toggle_history_panel(self, visible: bool) -> None:
        self.set_history_panel_visible(visible)

    def _toggle_experimental_pty(self, enabled: bool) -> None:
        if enabled == self._experimental_pty:
            return
        self.session.stop()
        self.output.clear()
        self._experimental_pty = enabled
        self.session = self._build_session(self._current_directory)
        self._bind_session()
        self.set_experimental_pty(enabled)
        self._ensure_session_started()

    def _rerun_last_command(self) -> None:
        if not self._recent_commands:
            return
        self._run_command(self._recent_commands[0])

    def _force_kill_current_program(self) -> None:
        self._show_action_status("Kill captured")
        self._append_output(f"\n[terminal] Kill captured for {self.session.backend_name}; forcing shell restart.\n")
        self.session.force_kill_current_program()
        self.output.set_input_ready(True)
        self.output.clear_draft()
        self.focus_input()

    def _show_action_status(self, action: str) -> None:
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        self.action_status_label.setText(f"{action} at {timestamp} ({self.session.backend_name})")
        self.action_status_label.setVisible(True)
        self.action_status_timer_start()

    def _ensure_session_started(self) -> bool:
        if not self.session.backend.is_running():
            self.session.start()
        return True

    def action_status_timer_start(self) -> None:
        self._action_status_timer.start()

    def _remember_command(self, command: str) -> None:
        cleaned = command.strip()
        if not cleaned:
            return
        command_key = self._command_key(cleaned)
        self._recent_commands = [
            existing
            for existing in self._recent_commands
            if self._command_key(existing) != command_key
        ]
        self._recent_commands.insert(0, cleaned)
        self._recent_commands = self._recent_commands[:100]
        self._refresh_command_lists()
        self._update_rerun_button()
        self.commands_changed.emit(self.recent_commands(), self.bookmarked_commands())

    def _refresh_command_lists(self) -> None:
        self.command_list.clear()
        pinned_keys = {
            self._command_key(command) for command in self._bookmarked_commands
        }
        ordered_commands = [
            (command, True) for command in self._bookmarked_commands
        ] + [
            (command, False)
            for command in self._recent_commands
            if self._command_key(command) not in pinned_keys
        ]
        for command, pinned in ordered_commands:
            item = QListWidgetItem(command)
            item.setSizeHint(QSize(0, 24))
            item.setData(_PINNED_COMMAND_ROLE, pinned)
            item.setToolTip(command)
            self.command_list.addItem(item)

    def _selected_command(self) -> str | None:
        current_item = self.command_list.currentItem()
        if current_item is not None:
            return current_item.text()
        text = self.output.current_draft().strip()
        return text or None

    def _selected_command_is_pinned(self) -> bool:
        current_item = self.command_list.currentItem()
        return bool(
            current_item is not None
            and current_item.data(_PINNED_COMMAND_ROLE)
        )

    def _run_clicked_command(self, item: QListWidgetItem) -> None:
        self._run_command(item.text())

    def _show_command_context_menu(self, position: QPoint) -> None:
        item = self.command_list.itemAt(position)
        if item is None:
            return

        self.command_list.setCurrentItem(item)
        self.command_list.setFocus(Qt.FocusReason.MouseFocusReason)
        command = item.text()
        menu = self._build_command_context_menu(
            command,
            pinned=bool(item.data(_PINNED_COMMAND_ROLE)),
        )
        menu.exec(self.command_list.viewport().mapToGlobal(position))

    def _build_command_context_menu(self, command: str, *, pinned: bool) -> QMenu:
        menu = QMenu(self)
        use_action = menu.addAction("Use command")
        use_action.triggered.connect(lambda _checked=False, value=command: self._use_command(value))
        run_action = menu.addAction("Run command")
        run_action.triggered.connect(lambda _checked=False, value=command: self._run_command(value))
        menu.addSeparator()

        if pinned:
            unpin_action = menu.addAction("Unpin command")
            unpin_action.triggered.connect(lambda _checked=False, value=command: self._remove_bookmark(value))
        else:
            pin_action = menu.addAction("Pin command")
            pin_action.setEnabled(command not in self._bookmarked_commands)
            pin_action.triggered.connect(lambda _checked=False, value=command: self._pin_command(value))

        return menu

    def _use_selected_command(self) -> None:
        command = self._selected_command()
        if command is None:
            return
        self._use_command(command)

    def _run_selected_command(self) -> None:
        command = self._selected_command()
        if command is None:
            return
        self._run_command(command)

    def _use_command(self, command: str) -> None:
        self.output.inject_command(command, run=False)
        self.focus_input()

    def _run_command(self, command: str) -> None:
        self.output.inject_command(command, run=True)

    def _pin_current_command(self) -> None:
        command = self._selected_command()
        if command is None:
            return
        self._pin_command(command)

    def _pin_command(self, command: str) -> None:
        if command in self._bookmarked_commands:
            return
        self._bookmarked_commands.append(command)
        self._refresh_command_lists()
        self.commands_changed.emit(self.recent_commands(), self.bookmarked_commands())

    def _remove_selected_bookmark(self) -> None:
        current_item = self.command_list.currentItem()
        if current_item is None or not current_item.data(_PINNED_COMMAND_ROLE):
            return
        self._remove_bookmark(current_item.text())

    def _remove_bookmark(self, command: str) -> None:
        if command not in self._bookmarked_commands:
            return
        self._bookmarked_commands.remove(command)
        self._refresh_command_lists()
        self.commands_changed.emit(self.recent_commands(), self.bookmarked_commands())

    def _update_rerun_button(self) -> None:
        self.rerun_action.setEnabled(bool(self._recent_commands))

    def _focus_first_command_list(self) -> None:
        if self.command_list.count() == 0:
            return
        self.command_list.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.command_list.setCurrentRow(0)

    def _unique_commands(self, commands: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for command in commands:
            cleaned = command.strip()
            command_key = self._command_key(cleaned)
            if not cleaned or command_key in seen:
                continue
            unique.append(cleaned)
            seen.add(command_key)
        return unique

    def _command_key(self, command: str) -> str:
        return command.strip()

    def _build_session(self, initial_directory: Path) -> TerminalSession:
        return TerminalSession(initial_directory=initial_directory, experimental_pty=self._experimental_pty)

    def _bind_session(self) -> None:
        self.output.set_sender(self.session.write_bytes)
        self.output.set_submit_sequence(self.session.submit_bytes())
        local_echo = self.session.backend_name == "qprocess"
        self.output.set_local_echo(local_echo)
        immediate_input = bool(getattr(self.output, "accepts_immediate_input", False))
        self.output.set_input_ready(local_echo or immediate_input)
        self._pty_ready_timer.stop()
        self._refresh_backend_ui()
        self.session.output_received.connect(self._append_output)
        self.session.started.connect(self._handle_started)

    def _resize_active_session(self, cols: int, rows: int) -> None:
        self.session.resize(cols, rows)

    def _refresh_backend_ui(self) -> None:
        backend_name = self.session.backend_name
        backend_label = {
            "conpty": "ConPTY",
            "winpty": "WinPTY",
            "qprocess": "Fallback",
            "posix-pty": "POSIX PTY",
        }.get(backend_name, backend_name)
        if self._experimental_pty:
            if backend_name == "qprocess":
                self.backend_status_label.setText("● Fallback")
                self.backend_status_label.setProperty("available", False)
                self.backend_status_label.setToolTip(
                    "PTY mode was requested, but the PTY backend is unavailable"
                )
            else:
                self.backend_status_label.setText(f"● {backend_label}")
                self.backend_status_label.setProperty("available", True)
                self.backend_status_label.setToolTip(f"Active terminal backend: {backend_label}")
        else:
            self.backend_status_label.setText("● Stable")
            self.backend_status_label.setProperty("available", True)
            self.backend_status_label.setToolTip("Stable line-oriented terminal backend")
        self.backend_status_label.style().unpolish(self.backend_status_label)
        self.backend_status_label.style().polish(self.backend_status_label)

    def _looks_ready_for_input(self) -> bool:
        text = self.output.toPlainText().rstrip()
        if not text:
            return False
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        if not lines:
            return False
        last_line = lines[-1]
        return bool(
            re.search(r"(?:[A-Za-z]:\\.*>|PS .*>|[$#] ?)$", last_line)
        )

    def _release_pty_input(self) -> None:
        if self.output.input_ready():
            return
        if not self._looks_ready_for_input():
            return
        self.output.set_input_ready(True)
