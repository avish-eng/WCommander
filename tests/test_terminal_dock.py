from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QListWidget, QPushButton

from multipane_commander.ui.terminal_dock import TerminalDock


_APP: QApplication | None = None


class FakeSignal:
    def connect(self, _handler) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.backend_name = "fake"
        self.shell_kind = "pwsh"
        self.output_received = FakeSignal()
        self.started = FakeSignal()
        self.interrupts = 0
        self.force_kills = 0
        self.starts = 0
        self.backend = self

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        return None

    def write_bytes(self, _data: bytes) -> None:
        return None

    def submit_bytes(self) -> bytes:
        return b"\r"

    def resize(self, _cols: int, _rows: int) -> None:
        return None

    def change_directory(self, _path: Path) -> None:
        return None

    def interrupt_current_program(self) -> None:
        self.interrupts += 1

    def force_kill_current_program(self) -> None:
        self.force_kills += 1

    def is_running(self) -> bool:
        return self.starts > 0


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

    assert dock.runtime_label.text() == "xterm.js · PowerShell 7"
    assert dock.backend_status_label.text() == "● ConPTY"
    assert "[terminal]" not in dock.output.toPlainText()


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
        "Use PTY backend",
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
    ]
    assert [action.text() for action in bookmark_menu.actions() if not action.isSeparator()] == [
        "Use command",
        "Run command",
        "Unpin command",
    ]


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
