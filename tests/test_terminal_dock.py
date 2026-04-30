from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from multipane_commander.ui.terminal_dock import TerminalDock


_APP: QApplication | None = None


class FakeSignal:
    def connect(self, _handler) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.backend_name = "fake"
        self.output_received = FakeSignal()
        self.started = FakeSignal()
        self.interrupts = 0
        self.force_kills = 0

    def start(self) -> None:
        return None

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
