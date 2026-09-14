from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from multipane_commander.terminal.deep.session import DeepTerminalSession


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


class FakeBackend(QObject):
    output_received = Signal(bytes)
    started = Signal()
    exited = Signal(int)
    failed = Signal(str)

    def __init__(self, *, is_pty: bool = True, running: bool = True) -> None:
        super().__init__()
        self.shell = SimpleNamespace(kind="posix")
        self.backend_name = "fake-pty" if is_pty else "pipe"
        self.is_pty = is_pty
        self.initial_directory = Path("/")
        self._running = running
        self.writes: list[str] = []
        self.starts = 0
        self.stops = 0
        self.interrupts = 0
        self.terminations = 0
        self.resizes: list[tuple[int, int]] = []

    def start(self) -> None:
        self.starts += 1
        self._running = True
        self.started.emit()

    def stop(self) -> None:
        self.stops += 1
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def write_bytes(self, data: bytes) -> None:
        self.writes.append(data.decode("utf-8", errors="replace"))

    def write_text(self, text: str) -> None:
        self.writes.append(text)

    def send_command(self, command: str) -> None:
        self.writes.append(command)

    def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))

    def interrupt_current_program(self) -> None:
        self.interrupts += 1

    def terminate_process_tree(self) -> None:
        self.terminations += 1


def _session(tmp_path: Path, *, is_pty: bool = True, running: bool = True):
    backend = FakeBackend(is_pty=is_pty, running=running)
    session = DeepTerminalSession(initial_directory=tmp_path, backend=backend)
    return session, backend


def test_session_forwards_raw_output_bytes_and_parses(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    received: list[bytes] = []
    session.output_received.connect(received.append)

    backend.output_received.emit(b"\x1b]0;title\x07hello")

    assert received == [b"\x1b]0;title\x07hello"]
    assert session.parser.title == "title"


def test_session_emits_cwd_changed_from_shell_integration(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    seen: list[Path] = []
    session.cwd_changed.connect(seen.append)

    backend.output_received.emit(b"\x1b]7;file:///home/dev/project\x07")

    assert seen == [Path("/home/dev/project")]
    assert session.known_directory == Path("/home/dev/project")


def test_session_emits_title_and_prompt_changes(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    titles: list[str] = []
    prompts: list[bool] = []
    session.title_changed.connect(titles.append)
    session.prompt_changed.connect(prompts.append)

    backend.output_received.emit(b"\x1b]2;deep shell\x07")
    backend.output_received.emit(b"\x1b]133;A\x07")

    assert titles == ["deep shell"]
    assert prompts == [True]


def test_session_emits_command_finished_and_detected(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    finished: list[int] = []
    detected: list[str] = []
    session.command_finished.connect(finished.append)
    session.command_detected.connect(detected.append)

    backend.output_received.emit(b"\x1b]133;P;k=i;cmd=ls -la\x07")
    backend.output_received.emit(b"\x1b]133;D;1\x07")

    assert detected == ["ls -la"]
    assert finished == [1]


def test_session_does_not_inject_directory_while_command_runs(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    backend.output_received.emit(b"dev@host:~$ ")

    session.write_bytes(b"sleep 5\r")
    target = tmp_path / "other"
    session.change_directory(target)

    assert backend.writes == ["sleep 5\r"]
    assert session.at_prompt is False


def test_session_injects_directory_once_at_prompt(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    backend.output_received.emit(b"dev@host:~$ ")
    target = tmp_path / "target"

    session.change_directory(target)
    session.change_directory(target)

    assert backend.writes == ["cd -- '" + str(target) + "'\n"]
    assert session.known_directory == target


def test_session_waits_for_prompt_before_injecting(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    target = tmp_path / "target"
    session.change_directory(target)
    assert backend.writes == []

    backend.output_received.emit(b"\x1b]133;A\x07")

    assert backend.writes == ["cd -- '" + str(target) + "'\n"]


def test_session_resyncs_after_manual_directory_change(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    backend.output_received.emit(b"dev@host:~$ ")

    backend.output_received.emit(b"\x1b]7;file:///tmp/manual\x07")
    session.change_directory(tmp_path / "wanted")

    assert backend.writes[-1] == "cd -- '" + str(tmp_path / "wanted") + "'\n"


def test_session_skips_injection_when_directory_already_matches(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    backend.output_received.emit(b"\x1b]7;" + tmp_path.as_uri().encode() + b"\x07")
    backend.output_received.emit(b"dev@host:~$ ")

    session.change_directory(tmp_path)

    assert backend.writes == []


def test_session_sync_attempts_are_bounded(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    backend.output_received.emit(b"dev@host:~$ ")
    session._desired_directory = tmp_path / "desired"
    session._known_directory = tmp_path / "known"
    session._last_sent_directory = tmp_path / "sent"
    session._sync_attempts = 3

    session._maybe_sync_directory()

    assert backend.writes == []


def test_session_submit_bytes_depends_on_backend(tmp_path: Path) -> None:
    _qapp()
    pty_session, _ = _session(tmp_path, is_pty=True)
    pipe_session, _ = _session(tmp_path, is_pty=False)

    assert pty_session.submit_bytes() == b"\r"
    assert pipe_session.submit_bytes() == b"\n"


def test_session_send_command_writes_command_and_submit(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)

    session.send_command("git status")

    assert backend.writes == ["git status", "\r"]


def test_session_resize_delegates(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)

    session.resize(120, 40)

    assert backend.resizes == [(120, 40)]


def test_session_force_kill_escalates_when_busy(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    backend.output_received.emit(b"dev@host:~$ ")
    session.write_bytes(b"sleep 5\r")

    session._escalate_kill()

    assert backend.terminations == 1


def test_session_force_kill_does_not_escalate_at_prompt(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    backend.output_received.emit(b"dev@host:~$ ")

    session._escalate_kill()

    assert backend.terminations == 0


def test_session_restart_stops_then_starts_on_exit(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path, running=True)

    session.restart()
    assert backend.stops == 1
    assert backend.starts == 0

    backend.exited.emit(0)

    assert backend.starts == 1


def test_session_restart_starts_immediately_when_not_running(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path, running=False)

    session.restart()

    assert backend.starts == 1
    assert backend.stops == 0


def test_session_decodes_utf8_split_across_chunks(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    encoded = "café ❯ ".encode("utf-8")

    backend.output_received.emit(encoded[:3])
    backend.output_received.emit(encoded[3:])

    assert "café" in session.parser.visible_text()


def test_session_forwards_backend_failure(tmp_path: Path) -> None:
    _qapp()
    session, backend = _session(tmp_path)
    messages: list[str] = []
    session.failed.connect(messages.append)

    backend.failed.emit("boom")

    assert messages == ["boom"]
