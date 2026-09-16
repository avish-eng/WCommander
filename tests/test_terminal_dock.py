from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QListWidget, QPushButton

from multipane_commander.ui.terminal_dock import TerminalDock
from deep_terminal_helpers import FakeDeepSession


_APP: QApplication | None = None


class FakeSession(FakeDeepSession):
    def __init__(self) -> None:
        super().__init__(Path.home())
        self.backend_name = "fake"


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def test_terminal_dock_copy_without_selection_does_not_interrupt(monkeypatch, tmp_path: Path) -> None:
    _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=True,
        follow_active_pane=True,
    )

    dock.copy_selected_text()

    assert fake_session.interrupts == 0


def test_terminal_dock_copy_with_selection_does_not_interrupt(monkeypatch, tmp_path: Path) -> None:
    _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=True,
        follow_active_pane=True,
    )
    dock.output.append_output("copy me")
    dock.output.selectAll()

    dock.copy_selected_text()

    assert fake_session.interrupts == 0


def test_terminal_dock_force_kill_delegates_to_session(monkeypatch, tmp_path: Path) -> None:
    _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=True,
        follow_active_pane=True,
    )

    dock.force_kill_current_program()

    assert fake_session.force_kills == 1


def test_terminal_dock_does_not_start_shell_when_hidden(monkeypatch, tmp_path: Path) -> None:
    _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)

    TerminalDock(
        initial_directory=tmp_path,
        visible=False,
        follow_active_pane=True,
    )

    assert fake_session.starts == 0


def test_terminal_dock_starts_shell_when_visible(monkeypatch, tmp_path: Path) -> None:
    _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)

    TerminalDock(
        initial_directory=tmp_path,
        visible=True,
        follow_active_pane=True,
    )

    assert fake_session.starts == 1


def test_terminal_dock_prefers_pty_for_xterm(monkeypatch, tmp_path: Path) -> None:
    fake_session = FakeSession()
    requested_modes: list[bool] = []

    def build_session(dock, _path):
        requested_modes.append(dock._experimental_pty)
        return fake_session

    monkeypatch.setattr("multipane_commander.ui.terminal_dock.WEB_TERMINAL_AVAILABLE", True)
    monkeypatch.setattr(TerminalDock, "_build_session", build_session)

    TerminalDock(
        initial_directory=tmp_path,
        visible=False,
        follow_active_pane=True,
        experimental_pty=False,
    )

    assert requested_modes == [True]


def test_terminal_dock_shows_frontend_shell_and_backend_beside_title(
    monkeypatch, tmp_path: Path
) -> None:
    _qapp()
    fake_session = FakeSession()
    fake_session.backend_name = "conpty"
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=False,
        follow_active_pane=True,
    )

    dock._handle_started()

    assert dock.runtime_label.text() == "xterm.js · PowerShell 7 · ConPTY"
    assert dock.findChild(QLabel, "terminalBackendStatus") is None
    assert "[terminal]" not in dock.output.toPlainText()


def test_terminal_dock_marks_unavailable_backend_in_runtime_status(
    monkeypatch, tmp_path: Path
) -> None:
    _qapp()
    fake_session = FakeSession()
    fake_session.backend_name = "qprocess"
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=False,
        follow_active_pane=True,
        experimental_pty=True,
    )

    assert dock.runtime_label.text().endswith(" · Fallback")
    assert dock.runtime_label.property("backendAvailable") is False
    assert "unavailable" in dock.runtime_label.toolTip()


def test_terminal_dock_moves_secondary_actions_into_overflow(
    monkeypatch, tmp_path: Path
) -> None:
    _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=False,
        follow_active_pane=True,
        recent_commands=["dir"],
    )

    assert [
        action.text() for action in dock.more_menu.actions() if not action.isSeparator()
    ] == [
        "Clear terminal",
        "Rerun last command",
        "Kill current process",
        "Use PTY on next launch",
        "Restart shell",
    ]
    assert dock.rerun_action.isEnabled()
    assert dock.pty_action.isCheckable()
    assert not dock.history_button.isHidden()


def test_terminal_history_uses_item_context_menus(monkeypatch, tmp_path: Path) -> None:
    app = _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=True,
        follow_active_pane=True,
        recent_commands=["dir"],
        bookmarked_commands=["cls"],
        history_panel_visible=True,
    )
    app.processEvents()

    assert dock.findChildren(QPushButton, "terminalHistoryActionButton") == []

    recent_menu = dock._build_command_context_menu("dir", pinned=False)
    bookmark_menu = dock._build_command_context_menu("cls", pinned=True)

    assert [action.text() for action in recent_menu.actions() if not action.isSeparator()] == [
        "Use command",
        "Run command",
        "Pin command",
        "Clear history (keeps pinned)",
    ]
    assert [action.text() for action in bookmark_menu.actions() if not action.isSeparator()] == [
        "Use command",
        "Run command",
        "Unpin command",
        "Clear history (keeps pinned)",
    ]

    # Right-clicking empty space still offers the clear action on its own.
    empty_menu = dock._build_command_context_menu(None, pinned=False)
    assert [action.text() for action in empty_menu.actions() if not action.isSeparator()] == [
        "Clear history (keeps pinned)",
    ]


def test_terminal_history_clear_keeps_pinned_commands(monkeypatch, tmp_path: Path) -> None:
    app = _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=True,
        follow_active_pane=True,
        recent_commands=["dir", "cls", "git status"],
        bookmarked_commands=["cls"],
        history_panel_visible=True,
    )
    app.processEvents()

    emitted: list[tuple[list[str], list[str]]] = []
    dock.commands_changed.connect(lambda recent, pinned: emitted.append((recent, pinned)))

    dock._clear_command_history()

    assert [dock.command_list.item(row).text() for row in range(dock.command_list.count())] == [
        "cls",
    ]
    assert dock.recent_commands() == []
    assert dock.bookmarked_commands() == ["cls"]
    assert emitted == [([], ["cls"])]
    assert not dock.rerun_action.isEnabled()

    # Clearing an already-empty history is a no-op and emits nothing further.
    dock._clear_command_history()
    assert len(emitted) == 1


def test_terminal_history_moves_repeated_command_to_the_top(monkeypatch, tmp_path: Path) -> None:
    app = _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=True,
        follow_active_pane=True,
        recent_commands=["dir", "cls", "git status"],
        history_panel_visible=True,
    )
    app.processEvents()

    dock._remember_command("git status")

    assert dock.recent_commands() == ["git status", "dir", "cls"]
    assert [dock.command_list.item(row).text() for row in range(dock.command_list.count())] == [
        "git status",
        "dir",
        "cls",
    ]

    # Surrounding whitespace is not a different command.
    dock._remember_command("  dir  ")
    assert dock.recent_commands() == ["dir", "git status", "cls"]


def test_terminal_history_uses_one_headerless_list_with_pinned_commands_first(
    monkeypatch, tmp_path: Path
) -> None:
    app = _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=True,
        follow_active_pane=True,
        recent_commands=["dir", "cls", "git status"],
        bookmarked_commands=["cls"],
        history_panel_visible=True,
    )
    app.processEvents()

    assert dock.findChild(QLineEdit, "terminalHistoryFilter") is None
    assert dock.findChildren(QLabel, "terminalHistorySection") == []
    assert dock.findChildren(QListWidget, "terminalCommandList") == [dock.command_list]
    assert [dock.command_list.item(row).text() for row in range(dock.command_list.count())] == [
        "cls",
        "dir",
        "git status",
    ]
    assert dock.command_list.item(0).data(Qt.ItemDataRole.UserRole) is True
    assert dock.command_list.item(1).data(Qt.ItemDataRole.UserRole) is False
    assert dock.command_list.property("pinnedTextColor") == QColor("#D8A144")


def test_terminal_history_caps_at_one_hundred_rows_keeping_pinned_and_newest(
    monkeypatch, tmp_path: Path
) -> None:
    app = _qapp()
    fake_session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: fake_session)
    dock = TerminalDock(
        initial_directory=tmp_path,
        visible=True,
        follow_active_pane=True,
        recent_commands=[f"cmd {index}" for index in range(150)],
        bookmarked_commands=["cls", "dir"],
        history_panel_visible=True,
    )
    app.processEvents()

    rows = [dock.command_list.item(row).text() for row in range(dock.command_list.count())]
    assert len(rows) == 100
    assert rows[:2] == ["cls", "dir"]
    # Recent commands stay newest-first and the oldest ones fall off the end.
    assert rows[2:5] == ["cmd 0", "cmd 1", "cmd 2"]
    assert rows[-1] == "cmd 97"

    dock._remember_command("brand new")
    rows = [dock.command_list.item(row).text() for row in range(dock.command_list.count())]
    assert len(rows) == 100
    assert rows[:3] == ["cls", "dir", "brand new"]
    assert rows[-1] == "cmd 96"

    # Pinning claims a slot from the recent commands rather than growing the list.
    dock._pin_command("cmd 0")
    rows = [dock.command_list.item(row).text() for row in range(dock.command_list.count())]
    assert len(rows) == 100
    assert rows[:4] == ["cls", "dir", "cmd 0", "brand new"]


def test_terminal_dock_records_confirmed_commands_not_raw_program_input(monkeypatch, tmp_path):
    _qapp()
    session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: session)
    dock = TerminalDock(initial_directory=tmp_path, visible=True, follow_active_pane=True)
    dock.output.command_submitted.emit("password-entered-into-program")
    assert dock.recent_commands() == []
    session.command_detected.emit("git status")
    assert dock.recent_commands() == ["git status"]


def test_terminal_dock_dispatch_uses_session_and_preserves_busy_program(monkeypatch, tmp_path):
    _qapp()
    session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: session)
    dock = TerminalDock(initial_directory=tmp_path, visible=True, follow_active_pane=True)
    session.at_prompt = False
    dock.inject_command(str(tmp_path), "git status")
    assert session.commands == []
    session.at_prompt = True
    dock.inject_command(str(tmp_path), "git status")
    assert session.commands == [("git status", tmp_path, True)]
    assert dock.recent_commands() == ["git status"]


def test_terminal_dock_pty_preference_keeps_running_session(monkeypatch, tmp_path):
    _qapp()
    session = FakeSession()
    monkeypatch.setattr(TerminalDock, "_build_session", lambda _self, _path: session)
    dock = TerminalDock(initial_directory=tmp_path, visible=True, follow_active_pane=True)
    active_runtime = dock.runtime_label.text()
    preferences = []
    dock.experimental_pty_toggled.connect(preferences.append)
    dock._toggle_experimental_pty(False)
    assert dock.session is session
    assert session.stops == 0
    assert session.starts == 1
    assert preferences == [False]
    assert dock.runtime_label.text() == active_runtime
