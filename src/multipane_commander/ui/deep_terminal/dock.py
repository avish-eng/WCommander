from __future__ import annotations

from pathlib import Path
from multipane_commander.ui.terminal_commands import TerminalCommands, populate_font_menu
import time

from PySide6.QtCore import QEvent, QPoint, QTime, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
)

from multipane_commander.terminal.deep.session import DeepTerminalSession
from multipane_commander.ui.command_history import (
    CommandHistoryDelegate,
    CommandHistoryList,
)
from multipane_commander.ui.deep_terminal.surface import (
    WEB_TERMINAL_AVAILABLE,
    XTERM_VERSION,
    DeepTerminalSurface,
    create_deep_surface,
)


_BACKEND_LABELS = {
    "conpty": "ConPTY",
    "winpty": "WinPTY",
    "posix-pty": "POSIX PTY",
    "pipe": "Pipe fallback",
}

_SHELL_LABELS = {
    "pwsh": "PowerShell 7",
    "powershell": "Windows PowerShell",
    "cmd": "Command Prompt",
    "posix": "POSIX shell",
}


class DeepTerminalDock(TerminalCommands, QFrame):
    """The Deep terminal: a fast, cross-platform PTY terminal dock.

    Streams raw PTY bytes to xterm.js in coalesced frames, tracks the shell
    prompt so directory following never types into a running program, and
    layers modern conveniences on top: search, clickable links, font zoom,
    native copy/paste, a command history panel and crash-safe restarts.
    """

    maximize_requested = Signal()
    follow_active_pane_toggled = Signal(bool)
    commands_changed = Signal(object, object)
    history_panel_visibility_changed = Signal(bool)
    experimental_pty_toggled = Signal(bool)
    font_size_changed = Signal(int)
    font_family_changed = Signal(str)

    def __init__(
        self,
        *,
        initial_directory: Path,
        visible: bool,
        follow_active_pane: bool,
        experimental_pty: bool = False,
        prefer_pty: bool = True,
        gpu_renderer: bool = False,
        font_family: str = "",
        font_size: int = 14,
        recent_commands: list[str] | None = None,
        bookmarked_commands: list[str] | None = None,
        history_panel_visible: bool = False,
        session_factory=None,
        surface_factory=None,
        auto_restart: bool = True,
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
        self._prefer_pty = prefer_pty
        self._gpu_renderer = gpu_renderer
        self._font_family = font_family.strip()
        self._base_font_size = max(6, min(40, int(font_size or 14)))
        self._font_size = self._base_font_size
        self._auto_restart = auto_restart
        self._terminated = False
        self._closing = False
        self._exit_restarts = 0
        self._last_exit_at = 0.0
        self._shell_title = ""
        self._recent_commands = self._unique_commands(recent_commands or [])
        self._bookmarked_commands = self._unique_commands(bookmarked_commands or [])
        self._trim_recent_commands()
        self._session_factory = session_factory
        self._surface_factory = surface_factory

        self.session = self._build_session(initial_directory)
        self.output = self._build_surface()

        self.title_label = QLabel("Shell")
        self.title_label.setObjectName("terminalTitle")
        self.runtime_label = QLabel()
        self.runtime_label.setObjectName("terminalRuntime")
        self.runtime_label.setWordWrap(False)
        self.runtime_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.runtime_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.action_status_label = QLabel()
        self.action_status_label.setObjectName("terminalActionStatus")
        self.action_status_label.setVisible(False)
        self._action_status_timer = QTimer(self)
        self._action_status_timer.setSingleShot(True)
        self._action_status_timer.setInterval(6000)
        self._action_status_timer.timeout.connect(self.action_status_label.hide)

        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("terminalToggleButton")
        self.search_button.setToolTip("Search terminal output (Ctrl+F)")
        self.search_button.clicked.connect(lambda _checked=False: self._toggle_search())
        self.follow_button = QPushButton()
        self.follow_button.setObjectName("terminalToggleButton")
        self.follow_button.setCheckable(True)
        self.follow_button.clicked.connect(self._toggle_follow_active_pane)
        self.history_button = QPushButton("History")
        self.history_button.setObjectName("terminalToggleButton")
        self.history_button.setCheckable(True)
        self.history_button.clicked.connect(self._toggle_history_panel)
        self.maximize_button = QPushButton("Expand")
        self.maximize_button.setObjectName("terminalCompactButton")
        self.maximize_button.clicked.connect(self.maximize_requested.emit)
        self.more_button = QPushButton("⋯")
        self.more_button.setObjectName("terminalMoreButton")
        self.more_button.setToolTip("More terminal actions")
        self.more_menu = self._build_more_menu()
        self.more_button.setMenu(self.more_menu)

        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(self.title_label)
        header.addWidget(self.runtime_label, 1)
        header.addWidget(self.action_status_label)
        header.addWidget(self.search_button)
        header.addWidget(self.history_button)
        header.addWidget(self.follow_button)
        header.addWidget(self.maximize_button)
        header.addWidget(self.more_button)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("terminalSearchInput")
        self.search_input.setPlaceholderText("Search terminal output…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.installEventFilter(self)
        self.search_case_button = QPushButton("Aa")
        self.search_case_button.setObjectName("terminalSearchNav")
        self.search_case_button.setCheckable(True)
        self.search_case_button.setToolTip("Match case")
        self.search_case_button.toggled.connect(lambda _checked=False: self._run_search(1))
        self.search_match_label = QLabel("0/0")
        self.search_match_label.setObjectName("terminalSearchMatch")
        self.search_prev_button = QPushButton("↑")
        self.search_prev_button.setObjectName("terminalSearchNav")
        self.search_prev_button.setToolTip("Previous match (Shift+Enter)")
        self.search_prev_button.clicked.connect(lambda _checked=False: self._run_search(-1))
        self.search_next_button = QPushButton("↓")
        self.search_next_button.setObjectName("terminalSearchNav")
        self.search_next_button.setToolTip("Next match (Enter)")
        self.search_next_button.clicked.connect(lambda _checked=False: self._run_search(1))
        self.search_close_button = QPushButton("✕")
        self.search_close_button.setObjectName("terminalSearchNav")
        self.search_close_button.setToolTip("Close search (Esc)")
        self.search_close_button.clicked.connect(lambda _checked=False: self._toggle_search(False))

        self.search_bar = QFrame()
        self.search_bar.setObjectName("terminalSearchBar")
        search_layout = QHBoxLayout(self.search_bar)
        search_layout.setContentsMargins(6, 3, 6, 3)
        search_layout.setSpacing(6)
        search_layout.addWidget(self.search_input, 1)
        search_layout.addWidget(self.search_match_label)
        search_layout.addWidget(self.search_case_button)
        search_layout.addWidget(self.search_prev_button)
        search_layout.addWidget(self.search_next_button)
        search_layout.addWidget(self.search_close_button)
        self.search_bar.setVisible(False)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(140)
        self._search_timer.timeout.connect(lambda: self._run_search(1))
        self.search_input.textChanged.connect(lambda _text: self._search_timer.start())

        self.output.viewport().installEventFilter(self)
        self.output.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.output.viewport().customContextMenuRequested.connect(self._show_terminal_context_menu)

        terminal_surface = QFrame()
        terminal_surface.setObjectName("terminalSurface")
        terminal_surface_layout = QVBoxLayout(terminal_surface)
        terminal_surface_layout.setContentsMargins(0, 0, 0, 0)
        terminal_surface_layout.setSpacing(0)
        terminal_surface_layout.addWidget(self.output, 1)

        self.command_list = CommandHistoryList()
        self.command_list.setObjectName("terminalCommandList")
        self.command_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.command_list.setSpacing(1)
        self.command_list.setUniformItemSizes(True)
        self.command_list.setItemDelegate(CommandHistoryDelegate(self.command_list))
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 8, 9, 9)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.search_bar)
        layout.addWidget(self.content_splitter, 1)

        self._bind_session()
        self._bind_surface()
        self.set_follow_active_pane(follow_active_pane)
        self.set_experimental_pty(True, emit=False)
        self.set_history_panel_visible(history_panel_visible, emit=False)
        self._refresh_command_lists()
        self._update_rerun_button()
        self._refresh_backend_ui()
        if visible:
            self._ensure_session_started()

    def _build_more_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("contextMenu")
        self.clear_action = menu.addAction("Clear terminal")
        self.clear_action.triggered.connect(lambda _checked=False: self.clear_terminal())
        self.save_image_action = menu.addAction("Save terminal image…")
        self.save_image_action.triggered.connect(
            lambda _checked=False: self._save_terminal_image()
        )
        self.rerun_action = menu.addAction("Rerun last command")
        self.rerun_action.triggered.connect(lambda _checked=False: self._rerun_last_command())
        self.interrupt_action = menu.addAction("Interrupt (Ctrl+C)")
        self.interrupt_action.triggered.connect(lambda _checked=False: self._interrupt_current_program())
        self.kill_action = menu.addAction("Kill current process")
        self.kill_action.triggered.connect(lambda _checked=False: self._force_kill_current_program())
        menu.addSeparator()
        self.copy_action = menu.addAction("Copy")
        self.copy_action.triggered.connect(lambda _checked=False: self.copy_selected_text())
        self.paste_action = menu.addAction("Paste")
        self.paste_action.triggered.connect(lambda _checked=False: self.paste_to_input())
        self.select_all_action = menu.addAction("Select all")
        self.select_all_action.triggered.connect(lambda _checked=False: self.output.selectAll())
        self.find_action = menu.addAction("Find…")
        self.find_action.triggered.connect(lambda _checked=False: self._toggle_search(True))
        menu.addSeparator()
        self.font_increase_action = menu.addAction("Increase font size")
        self.font_increase_action.triggered.connect(
            lambda _checked=False: self._adjust_font_size(1)
        )
        self.font_decrease_action = menu.addAction("Decrease font size")
        self.font_decrease_action.triggered.connect(
            lambda _checked=False: self._adjust_font_size(-1)
        )
        self.font_reset_action = menu.addAction("Reset font size")
        self.font_reset_action.triggered.connect(
            lambda _checked=False: self._reset_font_size()
        )
        self.font_menu = menu.addMenu("Font family")
        populate_font_menu(
            self,
            self.font_menu,
            current_family=self._font_family,
            on_selected=self._apply_font_family,
        )
        menu.addSeparator()
        self.pty_action = menu.addAction("Use PTY on next launch")
        self.pty_action.setCheckable(True)
        self.pty_action.setToolTip("Prefer a real pseudo-terminal (recommended)")
        self.pty_action.triggered.connect(self._toggle_experimental_pty)
        self.restart_action = menu.addAction("Restart shell")
        self.restart_action.triggered.connect(lambda _checked=False: self.restart_shell())
        return menu

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.search_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._toggle_search(False)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                direction = -1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
                self._run_search(direction)
                return True
        command_list = getattr(self, "command_list", None)
        if watched is command_list and command_list is not None and event.type() == QEvent.Type.KeyPress:
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
        focus = getattr(self.output, "focus_input", None)
        if callable(focus):
            focus()
            return
        self.output.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())
        if self.isVisible():
            self._ensure_session_started()
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
        if not enabled:
            self.session.cancel_directory_change()
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

    def set_experimental_pty(self, enabled: bool, *, emit: bool = True) -> None:
        self._prefer_pty = enabled
        self.pty_action.blockSignals(True)
        self.pty_action.setChecked(enabled)
        self.pty_action.blockSignals(False)
        self._refresh_backend_ui()
        if emit:
            self.experimental_pty_toggled.emit(enabled)

    def restart_shell(self) -> None:
        self.output.clear()
        self.session.restart()
        self._show_action_status("Restarting shell")

    def close_session(self) -> None:
        self._closing = True
        self.session.stop()

    def clear_terminal(self) -> None:
        self.output.clear()


    def copy_selected_text(self) -> None:
        self.output.copy()

    def cut_selected_text(self) -> None:
        return

    def paste_to_input(self) -> None:
        self.focus_input()
        paste = getattr(self.output, "paste_from_clipboard", None)
        if callable(paste):
            paste()
            return
        text = QApplication.clipboard().text()
        if text:
            self.output.inject_command(text, run=False)

    def force_kill_current_program(self) -> None:
        self._force_kill_current_program()

    def _build_session(self, initial_directory: Path) -> DeepTerminalSession:
        factory = self._session_factory
        if factory is not None:
            return factory(initial_directory, self._prefer_pty)
        return DeepTerminalSession(
            initial_directory=initial_directory,
            prefer_pty=self._prefer_pty,
        )

    def _build_surface(self) -> DeepTerminalSurface:
        factory = self._surface_factory
        if factory is not None:
            return factory(self)
        return create_deep_surface(
            self,
            gpu_renderer=self._gpu_renderer,
            font_family=self._font_family,
            font_size=self._base_font_size,
        )

    def _bind_session(self) -> None:
        self._prompt_was_ready = self.session.at_prompt
        self.output.set_sender(self.session.write_bytes)
        self.output.set_submit_sequence(self.session.submit_bytes())
        self.output.set_local_echo(not self.session.is_pty)
        self.output.set_input_ready(True)
        self.session.output_received.connect(self._append_output)
        self.session.started.connect(self._handle_started)
        self.session.exited.connect(self._handle_exited)
        self.session.failed.connect(self._handle_failed)
        self.session.cwd_changed.connect(self._handle_cwd_changed)
        self.session.title_changed.connect(self._handle_title_changed)
        self.session.prompt_changed.connect(self._handle_prompt_changed)
        self.session.command_detected.connect(self._handle_command_detected)

    def _bind_surface(self) -> None:
        self.output.command_submitted.connect(self._handle_typed_command)
        self.output.terminal_resized.connect(self._resize_active_session)
        self.output.font_size_changed.connect(self._handle_font_size_changed)
        self.output.link_activated.connect(self._open_link)
        self.output.search_requested.connect(lambda: self._toggle_search(True))
        self.output.search_result.connect(self._handle_search_result)
        self.output.title_received.connect(self._apply_title)
        self.output.bell_received.connect(lambda: self._show_action_status("Bell"))

    def _ensure_session_started(self) -> bool:
        try:
            if not self.session.is_running():
                self.session.start()
        except Exception as exc:
            self._handle_failed(str(exc))
        return True

    def _from_current_session(self) -> bool:
        sender = self.sender()
        return sender is None or sender is self.session

    def _append_output(self, data: bytes) -> None:
        if not self._from_current_session():
            return
        self.output.append_output(data)

    def _handle_started(self) -> None:
        if not self._from_current_session():
            return
        self.output.set_submit_sequence(self.session.submit_bytes())
        self.output.set_local_echo(not self.session.is_pty)
        self._refresh_backend_ui()
        self.output.set_input_ready(True)

    def _handle_exited(self, exit_code: int) -> None:
        if not self._from_current_session():
            return
        self._append_notice(f"\n[deep terminal] process exited with code {exit_code}\n")
        self._refresh_backend_ui()
        if self._closing or not self._auto_restart or not self.isVisible():
            return
        now = time.monotonic()
        if now - self._last_exit_at < 3.0:
            self._exit_restarts += 1
        else:
            self._exit_restarts = 0
        self._last_exit_at = now
        if self._exit_restarts > 3:
            self._append_notice("[deep terminal] auto-restart disabled after repeated exits\n")
            return
        QTimer.singleShot(150, self._ensure_session_started)

    def _handle_failed(self, message: str) -> None:
        if not self._from_current_session():
            return
        self._append_notice(f"\n[deep terminal] backend failed: {message}\n")
        self.runtime_label.setToolTip(f"Terminal backend failed: {message}")
        self._refresh_backend_ui()

    def _handle_cwd_changed(self, path: Path) -> None:
        if not self._from_current_session():
            return
        self._current_directory = path
        self._refresh_backend_ui()

    def _handle_title_changed(self, title: str) -> None:
        if not self._from_current_session():
            return
        self._apply_title(title)

    def _apply_title(self, title: str) -> None:
        cleaned = title.strip()
        if not cleaned:
            return
        self._shell_title = cleaned
        self.title_label.setText(f"Shell · {cleaned}")
        self.title_label.setToolTip(cleaned)

    def _handle_prompt_changed(self, at_prompt: bool) -> None:
        if not self._from_current_session():
            return
        if at_prompt and not self._prompt_was_ready:
            # TUI keys (for example q in a pager) are not a shell draft once
            # the session reports that the shell prompt has returned.
            self.output.clear_draft()
        self._prompt_was_ready = at_prompt
        self._refresh_backend_ui(at_prompt=at_prompt)

    def _handle_command_detected(self, command: str) -> None:
        if not self._from_current_session():
            return
        self._remember_command(command)

    def _handle_typed_command(self, command: str) -> None:
        # Only draft text that started at an idle shell prompt is a command;
        # input typed into a running child program (passwords, TUI keys) is
        # never written to history.
        if not self.session.draft_started_at_prompt:
            return
        self._remember_command(command)

    def _append_notice(self, text: str) -> None:
        self.output.append_output(text)

    def _open_link(self, uri: str) -> None:
        if not uri:
            return
        if uri.startswith(("http://", "https://", "file://")):
            QDesktopServices.openUrl(QUrl(uri))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(uri))

    def _toggle_search(self, visible: bool | None = None) -> None:
        if visible is None:
            visible = not self.search_bar.isVisible()
        self.search_bar.setVisible(visible)
        self.search_button.setProperty("active", visible)
        self.search_button.style().unpolish(self.search_button)
        self.search_button.style().polish(self.search_button)
        if visible:
            self.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.search_input.selectAll()
            if self.search_input.text():
                self._run_search(1)
            return
        self.search_match_label.setText("0/0")
        clear_search = getattr(self.output, "clear_search", None)
        if callable(clear_search):
            clear_search()
        self.focus_input()

    def _run_search(self, direction: int) -> None:
        query = self.search_input.text()
        if not query:
            self.search_match_label.setText("0/0")
            clear_search = getattr(self.output, "clear_search", None)
            if callable(clear_search):
                clear_search()
            return
        search = getattr(self.output, "search", None)
        if callable(search):
            search(
                query,
                direction=direction,
                case_sensitive=self.search_case_button.isChecked(),
            )

    def _handle_search_result(self, count: int, index: int) -> None:
        if count <= 0 or index < 0:
            self.search_match_label.setText("0/0")
            return
        self.search_match_label.setText(f"{index + 1}/{count}")

    def _adjust_font_size(self, delta: int) -> None:
        size = getattr(self.output, "font_size", None)
        current = size() if callable(size) else self._base_font_size
        self.output.set_font_size(current + delta)

    def _reset_font_size(self) -> None:
        self.output.set_font_size(self._base_font_size)

    def _handle_font_size_changed(self, size: int) -> None:
        self._font_size = max(6, min(40, int(size)))
        self.font_size_changed.emit(self._font_size)

    def _apply_font_family(self, family: str) -> None:
        self._font_family = family.strip()
        self.output.set_font_family(self._font_family)
        self._show_action_status(f"Font: {self._font_family or 'Default'}")
        self.font_family_changed.emit(self._font_family)

    def _toggle_follow_active_pane(self, enabled: bool) -> None:
        self.set_follow_active_pane(enabled)
        self.follow_active_pane_toggled.emit(enabled)

    def _toggle_history_panel(self, visible: bool) -> None:
        self.set_history_panel_visible(visible)

    def _toggle_experimental_pty(self, enabled: bool) -> None:
        self.set_experimental_pty(enabled)
        self._show_action_status("Backend preference saved for next launch")

    def _interrupt_current_program(self) -> None:
        self._show_action_status("Interrupt sent")
        self.session.interrupt_current_program()

    def _force_kill_current_program(self) -> None:
        self._show_action_status("Kill sent")
        self._append_notice("\n[deep terminal] forcing shell restart\n")
        self.session.force_kill_current_program()
        self.output.clear_draft()
        self.focus_input()

    def _show_action_status(self, action: str) -> None:
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        self.action_status_label.setText(f"{action} at {timestamp} ({self.session.backend_name})")
        self.action_status_label.setVisible(True)
        self.action_status_timer_start()

    def action_status_timer_start(self) -> None:
        self._action_status_timer.start()

    def _refresh_backend_ui(self, *, at_prompt: bool | None = None) -> None:
        label, available, tooltip = self._backend_description()
        shell = _SHELL_LABELS.get(self.session.shell_kind, self.session.shell_kind)
        frontend = f"xterm.js {XTERM_VERSION}" if WEB_TERMINAL_AVAILABLE else "Qt fallback"
        state = self._prompt_state(at_prompt)
        self.runtime_label.setText(f"{frontend} · {shell} · {label} · {state}")
        self.runtime_label.setProperty("backendAvailable", available)
        self.runtime_label.setProperty("promptState", state)
        full_tooltip = tooltip
        if self.session.known_directory:
            full_tooltip = f"{tooltip}\n{self.session.known_directory}"
        page_dpr = getattr(self.output, "page_device_pixel_ratio", None)
        page_dpr = page_dpr() if callable(page_dpr) else None
        if page_dpr:
            full_tooltip = (
                f"{full_tooltip}\nrender scale: page {page_dpr:.2f} / "
                f"widget {self.output.devicePixelRatioF():.2f}"
            )
        self.runtime_label.setToolTip(full_tooltip)
        self.runtime_label.style().unpolish(self.runtime_label)
        self.runtime_label.style().polish(self.runtime_label)
        self.pty_action.setChecked(self._prefer_pty)

    def _prompt_state(self, at_prompt: bool | None) -> str:
        if at_prompt is None:
            at_prompt = self.session.at_prompt
        if not self.session.is_running():
            return "stopped"
        return "ready" if at_prompt else "running"

    def _backend_description(self) -> tuple[str, bool, str]:
        backend_name = self.session.backend_name
        label = _BACKEND_LABELS.get(backend_name, backend_name)
        if backend_name == "pipe":
            return (
                label,
                False,
                "PTY unavailable; running in line-oriented pipe mode",
            )
        return label, True, f"Active terminal backend: {label}"

    def _resize_active_session(self, cols: int, rows: int) -> None:
        self.session.resize(cols, rows)


    def _show_terminal_context_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.triggered.connect(lambda _checked=False: self.copy_selected_text())
        paste_action = menu.addAction("Paste")
        paste_action.triggered.connect(lambda _checked=False: self.paste_to_input())
        select_all_action = menu.addAction("Select all")
        select_all_action.triggered.connect(lambda _checked=False: self.output.selectAll())
        menu.addSeparator()
        find_action = menu.addAction("Find…")
        find_action.triggered.connect(lambda _checked=False: self._toggle_search(True))
        clear_action = menu.addAction("Clear terminal")
        clear_action.triggered.connect(lambda _checked=False: self.clear_terminal())
        menu.addSeparator()
        interrupt_action = menu.addAction("Interrupt (Ctrl+C)")
        interrupt_action.triggered.connect(lambda _checked=False: self._interrupt_current_program())
        kill_action = menu.addAction("Kill current process")
        kill_action.triggered.connect(lambda _checked=False: self._force_kill_current_program())
        restart_action = menu.addAction("Restart shell")
        restart_action.triggered.connect(lambda _checked=False: self.restart_shell())
        viewport = self.output.viewport()
        menu.exec(viewport.mapToGlobal(position))
