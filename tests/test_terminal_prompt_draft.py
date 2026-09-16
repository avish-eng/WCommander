import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from multipane_commander.terminal.deep.session import DeepTerminalSession
from multipane_commander.ui.deep_terminal.dock import DeepTerminalDock
from multipane_commander.ui.deep_terminal.surface import DeepTerminalSurface
from multipane_commander.ui.terminal_dock import TerminalDock
from test_deep_session import FakeBackend


@pytest.fixture(params=["standard", "classic"])
def terminal(request, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    backend = FakeBackend()
    session = DeepTerminalSession(initial_directory=tmp_path, backend=backend)

    def surface(parent=None):
        return DeepTerminalSurface(parent, web_view_factory=lambda p: QWidget(p))

    if request.param == "standard":
        dock = DeepTerminalDock(initial_directory=tmp_path, visible=False,
                                follow_active_pane=True, session_factory=lambda *_: session,
                                surface_factory=surface, auto_restart=False)
    else:
        monkeypatch.setattr(TerminalDock, "_build_session", lambda *_: session)
        monkeypatch.setattr("multipane_commander.ui.terminal_dock.create_terminal_surface", surface)
        dock = TerminalDock(initial_directory=tmp_path, visible=False, follow_active_pane=True)
    backend.output_received.emit(b"user@host$ ")
    yield dock, session, backend
    dock.close_session()
    dock.close()
    app.processEvents()


def test_pager_quit_key_does_not_block_next_shell_command(terminal):
    dock, session, backend = terminal
    dock.output._handle_input(b"less file.txt\r")
    backend.output_received.emit(b"File contents\r\n(END)")
    dock.output._handle_input(b"q")
    assert dock.output.current_draft() == "q"
    assert not session.can_inject

    # Drive the actual parser/session signal path, including the order in
    # which prompt_changed and the session's dirty-input reset occur.
    backend.output_received.emit(b"\r\nuser@host$ ")
    assert session.can_inject
    assert dock.output.current_draft() == ""
    backend.writes.clear()
    assert dock._dispatch_command("echo ready")
    assert "echo ready" in "".join(backend.writes)
    assert dock.recent_commands() == ["echo ready"]


def test_pending_shell_draft_survives_repeated_ready_notification(terminal):
    dock, session, backend = terminal
    dock.output._handle_input(b"echo unfinished")
    assert session.at_prompt
    assert not session.can_inject
    session.prompt_changed.emit(True)
    assert dock.output.current_draft() == "echo unfinished"

    backend.writes.clear()
    assert not dock._dispatch_command("echo unintended")
    assert not backend.writes
    assert not dock.recent_commands()
