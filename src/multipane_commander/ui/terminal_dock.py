from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QEvent, QPoint, QPointF, QTime, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
)

from multipane_commander.terminal.session import TerminalSession
from multipane_commander.ui.terminal_surface import TerminalSurface


def _history_action_icon(kind: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#D7E7FF")
    accent = QColor("#4FD1FF")
    warning = QColor("#F27EA6")
    pen = QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if kind == "pin":
        painter.setPen(QPen(accent, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(6.0, 3.0), QPointF(11.0, 8.0))
        painter.drawLine(QPointF(4.5, 7.0), QPointF(9.0, 2.5))
        painter.drawLine(QPointF(7.0, 9.0), QPointF(3.2, 12.8))
        painter.drawLine(QPointF(9.0, 8.0), QPointF(12.5, 11.5))
    elif kind == "use":
        painter.setPen(QPen(accent, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(3.0, 5.0), QPointF(9.5, 5.0))
        painter.drawLine(QPointF(3.0, 8.0), QPointF(7.0, 8.0))
        painter.drawLine(QPointF(3.0, 11.0), QPointF(6.0, 11.0))
        painter.drawLine(QPointF(10.0, 7.0), QPointF(13.0, 10.0))
        painter.drawLine(QPointF(13.0, 10.0), QPointF(10.0, 13.0))
        painter.drawLine(QPointF(13.0, 10.0), QPointF(7.5, 10.0))
    elif kind == "run":
        painter.setPen(QPen(accent, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(accent)
        painter.drawPolygon(
            QPolygonF([QPointF(5.0, 3.5), QPointF(12.0, 8.0), QPointF(5.0, 12.5)])
        )
    elif kind == "unpin":
        painter.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(6.0, 3.0), QPointF(11.0, 8.0))
        painter.drawLine(QPointF(4.5, 7.0), QPointF(9.0, 2.5))
        painter.drawLine(QPointF(7.0, 9.0), QPointF(3.2, 12.8))
        painter.drawLine(QPointF(9.0, 8.0), QPointF(12.5, 11.5))
        painter.setPen(QPen(warning, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(3.2, 3.2), QPointF(12.8, 12.8))

    painter.end()
    return QIcon(pixmap)


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
        self._experimental_pty = experimental_pty
        self._recent_commands = self._unique_commands(recent_commands or [])
        self._bookmarked_commands = self._unique_commands(bookmarked_commands or [])
        self._output_press_pos: QPoint | None = None
        self._output_dragged = False
        self._pty_ready_timer = QTimer(self)
        self._pty_ready_timer.setSingleShot(True)
        self._pty_ready_timer.setInterval(150)
        self._pty_ready_timer.timeout.connect(self._release_pty_input)
        self.session = self._build_session(initial_directory)
        self.output = TerminalSurface()
        self.output.command_submitted.connect(self._remember_command)
        self.output.terminal_resized.connect(self._resize_active_session)
        self.cwd_label = QLabel(str(initial_directory))
        self.follow_button = QPushButton()
        self.pty_button = QPushButton()
        self.maximize_button = QPushButton("Full Screen")
        self.history_button = QPushButton("History")
        self.clear_button = QPushButton("Clear")
        self.rerun_button = QPushButton("Rerun")
        self.interrupt_button = QPushButton("Kill")
        self.action_status_label = QLabel()
        self._action_status_timer = QTimer(self)
        self._action_status_timer.setSingleShot(True)
        self._action_status_timer.setInterval(6000)
        self._action_status_timer.timeout.connect(self.action_status_label.hide)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header_top = QHBoxLayout()
        header_top.setSpacing(8)
        title = QLabel("Terminal")
        title.setObjectName("terminalTitle")
        self.cwd_label.setObjectName("terminalPath")
        self.cwd_label.setWordWrap(False)
        self.cwd_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cwd_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.follow_button.setObjectName("secondaryActionButton")
        self.follow_button.setCheckable(True)
        self.follow_button.clicked.connect(self._toggle_follow_active_pane)
        self.pty_button.setObjectName("secondaryActionButton")
        self.pty_button.setCheckable(True)
        self.pty_button.clicked.connect(self._toggle_experimental_pty)
        self.maximize_button.setObjectName("secondaryActionButton")
        self.maximize_button.clicked.connect(self.maximize_requested.emit)
        self.history_button.setObjectName("secondaryActionButton")
        self.history_button.setCheckable(True)
        self.history_button.clicked.connect(self._toggle_history_panel)
        self.clear_button.setObjectName("secondaryActionButton")
        self.clear_button.clicked.connect(self.output.clear)
        self.rerun_button.setObjectName("secondaryActionButton")
        self.rerun_button.clicked.connect(self._rerun_last_command)
        self.interrupt_button.setObjectName("secondaryActionButton")
        self.interrupt_button.setToolTip(
            "Force stop the current terminal process and restart the shell. Shortcut: Ctrl+Shift+K."
        )
        self.interrupt_button.clicked.connect(self._force_kill_current_program)
        self.action_status_label.setObjectName("terminalActionStatus")
        self.action_status_label.setVisible(False)
        restart_button = QPushButton("Restart Shell")
        restart_button.setObjectName("secondaryActionButton")
        restart_button.clicked.connect(self.restart_shell)

        header_top.addWidget(title)
        header_top.addWidget(self.cwd_label, 1)
        header_top.addWidget(self.history_button)
        header_top.addWidget(self.clear_button)
        header_top.addWidget(self.rerun_button)
        header_top.addWidget(self.interrupt_button)
        header_top.addWidget(self.action_status_label)
        header_top.addWidget(self.follow_button)
        header_top.addWidget(self.pty_button)
        header_top.addWidget(self.maximize_button)
        header_top.addWidget(restart_button)

        self.output.viewport().installEventFilter(self)

        terminal_surface = QFrame()
        terminal_surface.setObjectName("terminalSurface")
        terminal_surface_layout = QVBoxLayout(terminal_surface)
        terminal_surface_layout.setContentsMargins(0, 0, 0, 0)
        terminal_surface_layout.setSpacing(0)
        terminal_surface_layout.addWidget(self.output, 1)

        self.command_filter = QLineEdit()
        self.command_filter.setObjectName("terminalHistoryFilter")
        self.command_filter.setPlaceholderText("Filter command history")
        self.command_filter.textChanged.connect(self._refresh_command_lists)
        self.command_filter.installEventFilter(self)

        self.bookmarks_list = QListWidget()
        self.bookmarks_list.setObjectName("terminalCommandList")
        self.bookmarks_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.bookmarks_list.setSpacing(1)
        self.bookmarks_list.setUniformItemSizes(True)
        self.bookmarks_list.installEventFilter(self)
        self.recent_list = QListWidget()
        self.recent_list.setObjectName("terminalCommandList")
        self.recent_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.recent_list.setSpacing(1)
        self.recent_list.setUniformItemSizes(True)
        self.recent_list.installEventFilter(self)
        self.bookmarks_list.itemDoubleClicked.connect(self._run_clicked_command)
        self.recent_list.itemDoubleClicked.connect(self._run_clicked_command)
        self.bookmarks_list.currentItemChanged.connect(
            lambda current, _previous: self._clear_other_command_selection(self.recent_list, current)
        )
        self.recent_list.currentItemChanged.connect(
            lambda current, _previous: self._clear_other_command_selection(self.bookmarks_list, current)
        )

        history_panel = QFrame()
        history_panel.setObjectName("terminalHistoryPanel")
        history_panel.setMinimumWidth(260)
        history_layout = QVBoxLayout(history_panel)
        history_layout.setContentsMargins(10, 10, 10, 10)
        history_layout.setSpacing(6)
        bookmarks_title = QLabel("Pinned")
        bookmarks_title.setObjectName("terminalHistorySection")
        recent_title = QLabel("Recent")
        recent_title.setObjectName("terminalHistorySection")

        history_actions = QHBoxLayout()
        history_actions.setContentsMargins(0, 0, 0, 0)
        history_actions.setSpacing(4)
        pin_button = self._history_action_button("Pin command", "pin")
        pin_button.clicked.connect(self._pin_current_command)
        use_button = self._history_action_button("Use command", "use")
        use_button.clicked.connect(self._use_selected_command)
        run_button = self._history_action_button("Run command", "run")
        run_button.clicked.connect(self._run_selected_command)
        remove_button = self._history_action_button("Unpin command", "unpin")
        remove_button.clicked.connect(self._remove_selected_bookmark)
        history_actions.addWidget(pin_button)
        history_actions.addWidget(use_button)
        history_actions.addWidget(run_button)
        history_actions.addWidget(remove_button)

        history_layout.addWidget(self.command_filter)
        history_layout.addLayout(history_actions)
        history_layout.addWidget(bookmarks_title)
        history_layout.addWidget(self.bookmarks_list, 1)
        history_layout.addWidget(recent_title)
        history_layout.addWidget(self.recent_list, 1)
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
        self.set_experimental_pty(experimental_pty, emit=False)
        self.set_history_panel_visible(history_panel_visible, emit=False)
        self._refresh_command_lists()
        self._update_rerun_button()
        self.session.start()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        command_filter = getattr(self, "command_filter", None)
        bookmarks_list = getattr(self, "bookmarks_list", None)
        recent_list = getattr(self, "recent_list", None)

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
        elif watched is command_filter and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down and not event.modifiers():
                self._focus_first_command_list()
                return True
            if event.key() == Qt.Key.Key_Escape and not event.modifiers():
                self.focus_input()
                return True
        elif watched in {bookmarks_list, recent_list} and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
                self._run_selected_command()
                return True
            if event.key() == Qt.Key.Key_Delete and watched is bookmarks_list and not event.modifiers():
                self._remove_selected_bookmark()
                return True
            if event.matches(QKeySequence.StandardKey.Find):
                self.command_filter.setFocus(Qt.FocusReason.ShortcutFocusReason)
                self.command_filter.selectAll()
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
            self.focus_input()

    def set_maximized(self, maximized: bool) -> None:
        self._is_maximized = maximized
        self.maximize_button.setText("Exit Full Screen" if maximized else "Full Screen")
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
        self.cwd_label.setText(str(path))
        self.set_follow_active_pane(enabled)
        if enabled:
            self.session.change_directory(path)

    def set_follow_active_pane(self, enabled: bool) -> None:
        self._follow_active_pane = enabled
        self.follow_button.blockSignals(True)
        self.follow_button.setChecked(enabled)
        self.follow_button.blockSignals(False)
        self.follow_button.setText("Follow active pane" if enabled else "Independent cwd")
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
        self.pty_button.blockSignals(True)
        self.pty_button.setChecked(enabled)
        self.pty_button.blockSignals(False)
        self.pty_button.setProperty("active", enabled)
        self.pty_button.style().unpolish(self.pty_button)
        self.pty_button.style().polish(self.pty_button)
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
        if self.session.backend_name == "qprocess":
            self._append_output("Shell started.\n")

    def _toggle_follow_active_pane(self, enabled: bool) -> None:
        self.set_follow_active_pane(enabled)
        self.follow_active_pane_toggled.emit(enabled)

    def _toggle_history_panel(self, visible: bool) -> None:
        self.set_history_panel_visible(visible)

    def _toggle_experimental_pty(self, enabled: bool) -> None:
        if enabled == self._experimental_pty:
            return
        current_directory = Path(self.cwd_label.text())
        self.session.stop()
        self.output.clear()
        self._experimental_pty = enabled
        self.session = self._build_session(current_directory)
        self._bind_session()
        self.set_experimental_pty(enabled)
        self.session.start()

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
        filter_text = self.command_filter.text().strip().lower()
        self._fill_command_list(self.bookmarks_list, self._bookmarked_commands, filter_text)
        self._fill_command_list(self.recent_list, self._recent_commands, filter_text)

    def _fill_command_list(self, widget: QListWidget, commands: list[str], filter_text: str) -> None:
        widget.clear()
        for command in commands:
            if filter_text and filter_text not in command.lower():
                continue
            item = QListWidgetItem(command)
            item.setSizeHint(QSize(0, 24))
            widget.addItem(item)

    def _selected_command(self) -> str | None:
        if self.bookmarks_list.hasFocus():
            current_bookmark = self.bookmarks_list.currentItem()
            if current_bookmark is not None:
                return current_bookmark.text()
        if self.recent_list.hasFocus():
            current_recent = self.recent_list.currentItem()
            if current_recent is not None:
                return current_recent.text()
        current_bookmark = self.bookmarks_list.currentItem()
        current_recent = self.recent_list.currentItem()
        if current_bookmark is not None and current_recent is None:
            return current_bookmark.text()
        if current_recent is not None and current_bookmark is None:
            return current_recent.text()
        text = self.output.current_draft().strip()
        return text or None

    def _run_clicked_command(self, item: QListWidgetItem) -> None:
        self._run_command(item.text())

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
        if command in self._bookmarked_commands:
            return
        self._bookmarked_commands.append(command)
        self._refresh_command_lists()
        self.commands_changed.emit(self.recent_commands(), self.bookmarked_commands())

    def _remove_selected_bookmark(self) -> None:
        current_item = self.bookmarks_list.currentItem()
        if current_item is None:
            return
        command = current_item.text()
        if command not in self._bookmarked_commands:
            return
        self._bookmarked_commands.remove(command)
        self._refresh_command_lists()
        self.commands_changed.emit(self.recent_commands(), self.bookmarked_commands())

    def _update_rerun_button(self) -> None:
        self.rerun_button.setEnabled(bool(self._recent_commands))

    def _focus_first_command_list(self) -> None:
        target = self.bookmarks_list if self.bookmarks_list.count() else self.recent_list
        if target.count() == 0:
            return
        target.setFocus(Qt.FocusReason.ShortcutFocusReason)
        target.setCurrentRow(0)

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

    def _history_action_button(self, tooltip: str, icon_kind: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("terminalHistoryActionButton")
        button.setIcon(_history_action_icon(icon_kind))
        button.setIconSize(QSize(14, 14))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        return button

    def _clear_other_command_selection(self, other_list: QListWidget, current_item) -> None:
        if current_item is None:
            return
        other_list.clearSelection()
        other_list.setCurrentRow(-1)

    def _build_session(self, initial_directory: Path) -> TerminalSession:
        return TerminalSession(initial_directory=initial_directory, experimental_pty=self._experimental_pty)

    def _bind_session(self) -> None:
        self.output.set_sender(self.session.write_bytes)
        self.output.set_submit_sequence(self.session.submit_bytes())
        local_echo = self.session.backend_name == "qprocess"
        self.output.set_local_echo(local_echo)
        self.output.set_input_ready(local_echo)
        self._pty_ready_timer.stop()
        self._refresh_backend_ui()
        self.session.output_received.connect(self._append_output)
        self.session.started.connect(self._handle_started)

    def _resize_active_session(self, cols: int, rows: int) -> None:
        self.session.resize(cols, rows)

    def _refresh_backend_ui(self) -> None:
        backend_name = self.session.backend_name
        if self._experimental_pty:
            if backend_name == "qprocess":
                self.pty_button.setText("PTY Unavailable")
                self.pty_button.setToolTip("PTY mode was requested, but the PTY backend is unavailable. Using stable mode.")
            else:
                self.pty_button.setText("PTY Active")
                self.pty_button.setToolTip(f"Using PTY backend: {backend_name}")
            return
        self.pty_button.setText("Stable Mode")
        self.pty_button.setToolTip("Using the stable line-oriented terminal backend.")

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
