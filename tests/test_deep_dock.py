from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QListWidget, QPushButton, QWidget

from multipane_commander.ui.deep_terminal.dock import DeepTerminalDock
from multipane_commander.ui.deep_terminal.surface import DeepTerminalSurface


_APP: QApplication | None = None

_SHELL_KIND = "pwsh"


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


class FakeSession(QObject):
    output_received = Signal(bytes)
    started = Signal()
    exited = Signal(int)
    failed = Signal(str)
    cwd_changed = Signal(object)
    title_changed = Signal(str)
    prompt_changed = Signal(bool)
    command_finished = Signal(int)
    command_detected = Signal(str)

    def __init__(self, initial_directory: Path, prefer_pty: bool) -> None:
        super().__init__()
        self.initial_directory = initial_directory
        self.prefer_pty = prefer_pty
        self.backend_name = "conpty"
        self.shell_kind = _SHELL_KIND
        self.is_pty = True
        self.at_prompt = True
        self.known_directory = initial_directory
        self._running = False
        self.starts = 0
        self.stops = 0
        self.restarts = 0
        self.resizes: list[tuple[int, int]] = []
        self.directories: list[Path] = []
        self.interrupts = 0
        self.force_kills = 0

    def start(self) -> None:
        self.starts += 1
        self._running = True
        self.started.emit()

    def stop(self) -> None:
        self.stops += 1
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def restart(self) -> None:
        self.restarts += 1

    def write_bytes(self, _data: bytes) -> None:
        return

    def submit_bytes(self) -> bytes:
        return b"\r"

    def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))

    def change_directory(self, path: Path) -> None:
        self.directories.append(path)

    def interrupt_current_program(self) -> None:
        self.interrupts += 1

    def force_kill_current_program(self) -> None:
        self.force_kills += 1


def _dock(tmp_path: Path, *, visible: bool = False, auto_restart: bool = True):
    _qapp()
    sessions: list[FakeSession] = []

    def session_factory(path: Path, prefer_pty: bool) -> FakeSession:
        session = FakeSession(path, prefer_pty)
        sessions.append(session)
        return session

    dock = DeepTerminalDock(
        initial_directory=tmp_path,
        visible=visible,
        follow_active_pane=True,
        session_factory=session_factory,
        surface_factory=lambda parent: DeepTerminalSurface(
            parent, web_view_factory=lambda p: QWidget(p)
        ),
        auto_restart=auto_restart,
    )
    return dock, sessions


def test_deep_dock_does_not_start_shell_when_hidden(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=False)

    assert sessions[0].starts == 0
    assert dock.title_label.text() == "Deep Terminal"


def test_deep_dock_starts_shell_when_visible(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=True)

    assert sessions[0].starts == 1


def test_deep_dock_toggle_visible_starts_and_focuses(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=False)

    dock.toggle_visible()

    assert dock.isVisible()
    assert sessions[0].starts == 1

    dock.toggle_visible()
    assert not dock.isVisible()


def test_deep_dock_keeps_api_surface_used_by_main_window(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=True)

    for attribute in (
        "session",
        "output",
        "runtime_label",
        "follow_button",
        "maximize_button",
        "history_button",
        "more_button",
        "more_menu",
        "clear_action",
        "rerun_action",
        "kill_action",
        "pty_action",
        "restart_action",
        "command_list",
        "history_panel",
        "content_splitter",
        "action_status_label",
    ):
        assert hasattr(dock, attribute), attribute

    for method in (
        "focus_input",
        "toggle_visible",
        "inject_command",
        "set_maximized",
        "set_side_by_side_mode",
        "sync_to_path",
        "set_follow_active_pane",
        "set_history_panel_visible",
        "restart_shell",
        "close_session",
        "set_experimental_pty",
        "recent_commands",
        "bookmarked_commands",
        "copy_selected_text",
        "cut_selected_text",
        "force_kill_current_program",
        "paste_to_input",
        "_ensure_session_started",
    ):
        assert callable(getattr(dock, method)), method


def test_deep_dock_runtime_label_reports_engine_and_prompt_state(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)

    dock._handle_prompt_changed(False)
    assert "ConPTY" in dock.runtime_label.text()
    assert "running" in dock.runtime_label.text()

    dock._handle_prompt_changed(True)
    assert "ready" in dock.runtime_label.text()
    assert dock.runtime_label.property("backendAvailable") is True


def test_deep_dock_marks_pipe_backend_unavailable(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=False)
    sessions[0].backend_name = "pipe"
    sessions[0].is_pty = False

    dock._refresh_backend_ui()

    assert dock.runtime_label.property("backendAvailable") is False
    assert "Pipe fallback" in dock.runtime_label.text()


def test_deep_dock_updates_title_from_shell(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)

    dock._handle_title_changed("~/project — zsh")

    assert "~/project — zsh" in dock.title_label.text()
    assert dock.title_label.toolTip() == "~/project — zsh"


def test_deep_dock_follow_toggle_emits(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=False)
    emitted: list[bool] = []
    dock.follow_active_pane_toggled.connect(emitted.append)

    dock.follow_button.click()

    assert emitted == [False]
    assert dock.follow_button.text() == "Independent"


def test_deep_dock_sync_to_path_forwards_when_enabled(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=True)
    target = tmp_path / "other"

    dock.sync_to_path(target, enabled=False)
    assert sessions[0].directories == []

    dock.sync_to_path(target, enabled=True)
    assert sessions[0].directories == [target]


def test_deep_dock_inject_command_navigates_and_runs(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=True)
    injected: list[tuple[str, bool]] = []
    dock.output.inject_command = lambda command, run: injected.append((command, run))

    dock.inject_command(str(tmp_path / "work"), "make test")

    assert sessions[0].directories == [tmp_path / "work"]
    assert injected == [("make test", True)]


def test_deep_dock_history_moves_repeated_command_to_top(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)
    dock._recent_commands = ["dir", "cls", "git status"]

    dock._remember_command("git status")

    assert dock.recent_commands() == ["git status", "dir", "cls"]


def test_deep_dock_history_caps_and_keeps_pinned(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)
    dock._recent_commands = [f"cmd {index}" for index in range(150)]
    dock._bookmarked_commands = ["cls", "dir"]
    dock._trim_recent_commands()
    dock._refresh_command_lists()

    rows = [dock.command_list.item(row).text() for row in range(dock.command_list.count())]
    assert len(rows) == 100
    assert rows[:2] == ["cls", "dir"]
    assert rows[-1] == "cmd 97"
    assert dock.command_list.item(0).data(Qt.ItemDataRole.UserRole) is True
    assert dock.command_list.property("pinnedTextColor") == QColor("#D8A144")


def test_deep_dock_clear_history_keeps_pinned(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)
    dock._recent_commands = ["dir", "cls"]
    dock._bookmarked_commands = ["cls"]
    dock._refresh_command_lists()
    emitted: list[tuple[list[str], list[str]]] = []
    dock.commands_changed.connect(lambda recent, pinned: emitted.append((recent, pinned)))

    dock._clear_command_history()

    assert dock.recent_commands() == []
    assert dock.bookmarked_commands() == ["cls"]
    assert emitted == [([], ["cls"])]
    assert not dock.rerun_action.isEnabled()


def test_deep_dock_command_context_menu_has_pin_and_clear(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)

    recent_menu = dock._build_command_context_menu("dir", pinned=False)
    pinned_menu = dock._build_command_context_menu("cls", pinned=True)
    empty_menu = dock._build_command_context_menu(None, pinned=False)

    assert [action.text() for action in recent_menu.actions() if not action.isSeparator()] == [
        "Use command",
        "Run command",
        "Pin command",
        "Clear history (keeps pinned)",
    ]
    assert [action.text() for action in pinned_menu.actions() if not action.isSeparator()] == [
        "Use command",
        "Run command",
        "Unpin command",
        "Clear history (keeps pinned)",
    ]
    assert [action.text() for action in empty_menu.actions() if not action.isSeparator()] == [
        "Clear history (keeps pinned)",
    ]


def test_deep_dock_more_menu_exposes_modern_actions(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True, )

    labels = [action.text() for action in dock.more_menu.actions() if not action.isSeparator()]

    assert labels == [
        "Clear terminal",
        "Rerun last command",
        "Interrupt (Ctrl+C)",
        "Kill current process",
        "Copy",
        "Paste",
        "Select all",
        "Find…",
        "Increase font size",
        "Decrease font size",
        "Reset font size",
        "Use PTY backend",
        "Restart shell",
    ]
    assert dock.pty_action.isChecked()


def test_deep_dock_interrupt_and_kill_delegate_to_session(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=True)

    dock.force_kill_current_program()
    dock._interrupt_current_program()

    assert sessions[0].force_kills == 1
    assert sessions[0].interrupts == 1


def test_deep_dock_restart_shell_clears_and_restarts(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=True)

    dock.restart_shell()

    assert sessions[0].restarts == 1
    assert dock.output.toPlainText() == ""


def test_deep_dock_close_session_stops_backend(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=True)

    dock.close_session()

    assert dock._closing is True
    assert sessions[0].stops == 1


def test_deep_dock_exited_auto_restarts_when_visible(tmp_path: Path, monkeypatch) -> None:
    dock, sessions = _dock(tmp_path, visible=True)
    monkeypatch.setattr(
        "multipane_commander.ui.deep_terminal.dock.QTimer.singleShot",
        lambda _ms, callback: callback(),
    )

    dock._handle_exited(0)

    assert sessions[0].starts == 1
    assert "[deep terminal] process exited with code 0" in dock.output.toPlainText()


def test_deep_dock_exited_does_not_restart_when_hidden(tmp_path: Path, monkeypatch) -> None:
    dock, sessions = _dock(tmp_path, visible=False)
    monkeypatch.setattr(
        "multipane_commander.ui.deep_terminal.dock.QTimer.singleShot",
        lambda _ms, callback: callback(),
    )

    dock._handle_exited(1)

    assert sessions[0].starts == 0


def test_deep_dock_disables_auto_restart_after_repeated_exits(tmp_path: Path, monkeypatch) -> None:
    dock, sessions = _dock(tmp_path, visible=True)
    monkeypatch.setattr(
        "multipane_commander.ui.deep_terminal.dock.QTimer.singleShot",
        lambda _ms, callback: callback(),
    )
    monkeypatch.setattr(
        "multipane_commander.ui.deep_terminal.dock.time.monotonic",
        lambda: 0.0,
    )

    for _ in range(6):
        dock._handle_exited(1)

    assert sessions[0].starts == 1
    assert "auto-restart disabled" in dock.output.toPlainText()


def test_deep_dock_toggle_pty_rebuilds_session(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=True)
    emitted: list[bool] = []
    dock.experimental_pty_toggled.connect(emitted.append)

    dock._toggle_experimental_pty(False)

    assert len(sessions) == 2
    assert sessions[0].stops == 1
    assert sessions[1].prefer_pty is False
    assert sessions[1].starts == 1
    assert emitted == [False]


def test_deep_dock_ignores_signals_from_replaced_session(tmp_path: Path, monkeypatch) -> None:
    dock, sessions = _dock(tmp_path, visible=True)
    old = sessions[0]
    monkeypatch.setattr(
        "multipane_commander.ui.deep_terminal.dock.QTimer.singleShot",
        lambda _ms, callback: callback(),
    )

    dock._toggle_experimental_pty(False)
    new = sessions[1]
    assert new.starts == 1

    old.exited.emit(0)
    old.output_received.emit(b"stale-output")
    old.prompt_changed.emit(True)

    assert new.starts == 1
    assert "stale-output" not in dock.output.toPlainText()


def test_deep_dock_search_toggle_and_run(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)
    dock._toggle_search(True)
    assert dock.search_bar.isVisible()

    calls: list[tuple[str, int, bool]] = []
    dock.output.search = lambda query, direction, case_sensitive: calls.append(
        (query, direction, case_sensitive)
    )
    dock.search_input.setText("needle")
    dock._run_search(1)
    calls.clear()
    dock.search_case_button.setChecked(True)
    dock._run_search(-1)

    assert calls == [
        ("needle", 1, True),
        ("needle", -1, True),
    ]

    dock._handle_search_result(4, 2)
    assert dock.search_match_label.text() == "3/4"

    dock._handle_search_result(0, -1)
    assert dock.search_match_label.text() == "0/0"


def test_deep_dock_empty_search_resets_label(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)
    dock.search_input.setText("")
    dock.search_match_label.setText("9/9")

    dock._run_search(1)

    assert dock.search_match_label.text() == "0/0"


def test_deep_dock_search_close_hides_bar(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)
    dock._toggle_search(True)

    dock._toggle_search(False)

    assert not dock.search_bar.isVisible()
    assert dock.search_match_label.text() == "0/0"


def test_deep_dock_resize_forwards_to_session(tmp_path: Path) -> None:
    dock, sessions = _dock(tmp_path, visible=True)

    dock._resize_active_session(120, 40)

    assert sessions[0].resizes == [(120, 40)]


def test_deep_dock_set_maximized_and_side_by_side(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)

    dock.set_maximized(True)
    assert dock.maximize_button.text() == "Restore"

    dock.set_side_by_side_mode(True)
    assert dock.minimumHeight() == 0

    dock.set_maximized(False)
    dock.set_side_by_side_mode(False)
    assert dock.minimumHeight() == 220
    assert dock.maximize_button.text() == "Expand"


def test_deep_dock_open_link_routes_to_desktop_services(tmp_path: Path, monkeypatch) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)
    opened: list[str] = []
    monkeypatch.setattr(
        "multipane_commander.ui.deep_terminal.dock.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    dock._open_link("https://example.com/x")
    dock._open_link("/tmp/local-file.txt")

    assert opened[0] == "https://example.com/x"
    assert opened[1].startswith("file:")


def test_deep_dock_has_no_legacy_history_filter_widget(tmp_path: Path) -> None:
    dock, _sessions = _dock(tmp_path, visible=True)

    assert dock.findChild(QLineEdit, "terminalHistoryFilter") is None
    assert dock.findChildren(QLabel, "terminalHistorySection") == []
    assert dock.findChildren(QListWidget, "terminalCommandList") == [dock.command_list]
    assert dock.findChildren(QPushButton, "terminalHistoryActionButton") == []