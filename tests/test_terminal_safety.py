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
    def surface(parent=None, **_kwargs):
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


def test_child_program_input_is_never_saved_as_command_history(terminal):
    dock, session, backend = terminal
    saved = []
    dock.commands_changed.connect(lambda *args: saved.append(args))
    dock.output._handle_input(b"program-requesting-password\r")
    backend.output_received.emit(b"Password: ")
    dock.output._handle_input(b"SYNTHETIC_TEST_SECRET\r")
    assert not session.at_prompt
    # The shell command that launched the program is recorded; the secret
    # typed into the child program is not.
    assert dock.recent_commands() == ["program-requesting-password"]
    assert len(saved) == 1


def test_typed_command_at_idle_prompt_is_saved(terminal):
    dock, session, backend = terminal
    dock.output._handle_input(b"git status\r")
    backend.output_received.emit(b"\r\nuser@host$ ")
    assert dock.recent_commands() == ["git status"]

    dock.output._handle_input(b"ls -la\r")
    backend.output_received.emit(b"\r\nuser@host$ ")
    assert dock.recent_commands() == ["ls -la", "git status"]


def test_explicit_command_is_saved_and_cwd_is_part_of_guarded_command(terminal, tmp_path):
    dock, session, backend = terminal
    destination = tmp_path / "target folder"
    destination.mkdir()
    dock.inject_command(str(destination), "echo requested")
    combined = "".join(backend.writes)
    assert str(destination) in combined
    assert "&& { echo requested" in combined
    assert dock.recent_commands() == ["echo requested"]
    assert not session.at_prompt


@pytest.mark.parametrize("draft", [b"interactive-program\r", b"echo unfinished"])
def test_ui_run_and_use_commands_do_not_write_into_busy_or_unfinished_input(terminal, draft):
    dock, session, backend = terminal
    dock.output._handle_input(draft)
    backend.writes.clear()
    dock._run_command("echo unintended")
    dock._use_command("echo unintended")
    assert not backend.writes
    assert "wait for the shell prompt" in dock.action_status_label.text()
    assert "echo unintended" not in dock.recent_commands()


def test_folder_follow_waits_for_unfinished_command_to_finish(terminal, tmp_path):
    dock, session, backend = terminal
    dock.output._handle_input(b"echo draft")
    backend.writes.clear()
    dock.sync_to_path(tmp_path / "other", enabled=True)
    assert not backend.writes
    dock.output._handle_input(b"\r")
    backend.output_received.emit(b"\r\nuser@host$ ")
    assert any("other" in write and "cd " in write for write in backend.writes)


def test_independent_mode_cancels_pending_folder_follow(terminal, tmp_path):
    dock, session, backend = terminal
    dock.output._handle_input(b"long-task\r")
    backend.output_received.emit(b"working\r\n")
    dock.sync_to_path(tmp_path / "other", enabled=True)
    dock.set_follow_active_pane(False)
    backend.writes.clear()
    backend.output_received.emit(b"user@host$ ")
    assert not backend.writes


def test_missing_command_directory_is_rejected(terminal, tmp_path):
    dock, session, backend = terminal
    dock.inject_command(str(tmp_path / "missing"), "echo should-not-run")
    assert not backend.writes
    assert not dock.recent_commands()


def test_standard_and_classic_share_renderer_and_session_core():
    from multipane_commander.ui.xterm_surface import XtermTerminalSurface
    from multipane_commander.terminal.session import TerminalSession
    assert XtermTerminalSurface is DeepTerminalSurface
    assert issubclass(TerminalSession, DeepTerminalSession)


def test_follow_returns_to_original_directory_after_shell_reports_manual_cd(terminal, tmp_path):
    dock, session, backend = terminal
    elsewhere = tmp_path / "elsewhere"
    dock.output._handle_input(b"cd elsewhere\r")
    backend.output_received.emit(("PS " + str(elsewhere) + "> ").encode())
    assert session.known_directory == elsewhere
    backend.writes.clear()
    dock.sync_to_path(tmp_path, enabled=True)
    assert any(str(tmp_path) in command and "cd " in command for command in backend.writes)


@pytest.mark.skipif(os.name != "nt", reason="Windows shell integration")
@pytest.mark.parametrize("shell_kind", ["cmd", "pwsh"])
def test_real_windows_shell_dispatch_and_deferred_follow(tmp_path, shell_kind):
    from pathlib import Path
    import shutil
    from multipane_commander.platform import ShellSpec
    from ui_wait import wait_until
    app = QApplication.instance() or QApplication([])
    target = tmp_path / "folder with spaces"
    target.mkdir()
    if shell_kind == "pwsh":
        program = shutil.which("pwsh")
        if program is None:
            pytest.skip("PowerShell 7 is not installed")
        shell = ShellSpec(program=program, args=["-NoLogo", "-NoProfile", "-NoExit", "-Command", "Remove-Module PSReadLine -ErrorAction SilentlyContinue"], kind="pwsh")
    else:
        shell = ShellSpec(program=str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe"),
                          args=["/D", "/Q"], kind="cmd")
    session = DeepTerminalSession(initial_directory=tmp_path, shell=shell)
    captured = []
    session.output_received.connect(captured.append)
    try:
        session.start()
        wait_until(lambda: session.can_inject, timeout=15)
        assert session.submit_command("echo __COMMAND_RAN__", cwd=target)
        wait_until(lambda: session.can_inject and session.known_directory == target, timeout=15)
        assert b"__COMMAND_RAN__" in b"".join(captured)
        session.write_text("echo unfinished")
        session.change_directory(tmp_path)
        assert not session.submit_command("echo __MUST_NOT_RUN__")
        session.write_bytes(b"\r")
        wait_until(lambda: session.can_inject and session.known_directory == tmp_path, timeout=15)
        assert b"__MUST_NOT_RUN__" not in b"".join(captured)
    finally:
        session.stop()
        wait_until(lambda: not session.is_running(), timeout=10)
        wait_until(lambda: session.backend._spawn_thread is None or
                   not session.backend._spawn_thread.is_alive(), timeout=10)
        app.processEvents()


def test_pipe_fallback_updates_echo_and_submit_sequence(terminal):
    dock, session, backend = terminal
    backend.is_pty = False
    backend.shell.kind = "cmd"
    backend.backend_name = "pipe"
    backend.started.emit()
    assert dock.output._local_echo is True
    assert dock.output._submit_sequence == b"\r\n"


def test_terminal_protocol_replies_do_not_create_a_user_draft(terminal):
    dock, session, backend = terminal
    session.write_bytes(b"\x1b[1;1R")
    session.write_bytes(b"\x1b[?1;2c")
    assert session.can_inject
