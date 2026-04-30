from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

from multipane_commander.terminal.backends import QProcessBackend, WinPtyBackend
from multipane_commander.terminal.session import TerminalSession


class FakeBackend:
    def __init__(self) -> None:
        self.shell = type("Shell", (), {"kind": "posix"})()
        self.backend_name = "fake"
        self.writes: list[str] = []
        self.running = True

    class _Signal:
        def connect(self, _handler) -> None:
            return None

    output_received = _Signal()
    started = _Signal()

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def send_command(self, command: str) -> None:
        self.writes.append(f"command:{command}")

    def write_text(self, text: str) -> None:
        self.writes.append(text)

    def write_bytes(self, data: bytes) -> None:
        self.writes.append(data.decode("utf-8", errors="replace"))

    def interrupt_current_program(self) -> None:
        self.writes.append("interrupt")

    def force_kill_current_program(self) -> None:
        self.writes.append("force-kill")

    def is_running(self) -> bool:
        return self.running


def test_terminal_session_uses_selected_backend(monkeypatch) -> None:
    backend = FakeBackend()
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        "multipane_commander.terminal.session.create_terminal_backend",
        lambda initial_directory, experimental_pty=False: seen.update(
            {"initial_directory": initial_directory, "experimental_pty": experimental_pty}
        )
        or backend,
    )

    session = TerminalSession(initial_directory=Path.home(), experimental_pty=True)

    assert session.backend is backend
    assert session.backend_name == "fake"
    assert session.shell_kind == "posix"
    assert seen == {
        "initial_directory": Path.home(),
        "experimental_pty": True,
    }


def test_terminal_session_hides_directory_sync_command(monkeypatch, tmp_path: Path) -> None:
    backend = FakeBackend()
    monkeypatch.setattr(
        "multipane_commander.terminal.session.create_terminal_backend",
        lambda initial_directory, experimental_pty=False: backend,
    )

    session = TerminalSession(initial_directory=tmp_path)
    target = tmp_path / "folder"

    session.change_directory(target)

    assert backend.writes == ["cd -- '" + str(target) + "'\n"]
    assert session._strip_hidden_commands("cd -- '" + str(target) + "'\nhello") == "\nhello"


def test_terminal_session_uses_carriage_return_for_pty_submit(monkeypatch) -> None:
    backend = FakeBackend()
    backend.shell = type("Shell", (), {"kind": "cmd"})()
    backend.backend_name = "winpty"
    monkeypatch.setattr(
        "multipane_commander.terminal.session.create_terminal_backend",
        lambda initial_directory, experimental_pty=False: backend,
    )

    session = TerminalSession(initial_directory=Path.home(), experimental_pty=True)

    assert session.submit_bytes() == b"\r"


def test_terminal_session_interrupts_current_program(monkeypatch) -> None:
    backend = FakeBackend()
    monkeypatch.setattr(
        "multipane_commander.terminal.session.create_terminal_backend",
        lambda initial_directory, experimental_pty=False: backend,
    )

    session = TerminalSession(initial_directory=Path.home())
    session.interrupt_current_program()

    assert backend.writes == ["interrupt"]


def test_terminal_session_force_kills_current_program(monkeypatch) -> None:
    backend = FakeBackend()
    monkeypatch.setattr(
        "multipane_commander.terminal.session.create_terminal_backend",
        lambda initial_directory, experimental_pty=False: backend,
    )

    session = TerminalSession(initial_directory=Path.home())
    session.force_kill_current_program()

    assert backend.writes == ["force-kill"]


def test_winpty_backend_forces_winpty_engine(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.alive = True

        def isalive(self) -> bool:
            return self.alive

        def read(self) -> str:
            self.alive = False
            raise EOFError

        def terminate(self) -> None:
            self.alive = False

    class FakePtyProcess:
        @staticmethod
        def spawn(_argv, **kwargs):
            calls.append(kwargs)
            return FakeProcess()

    winpty_backend = object()
    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            Backend=SimpleNamespace(WinPTY=winpty_backend),
            PtyProcess=FakePtyProcess,
        ),
    )

    backend = WinPtyBackend(initial_directory=tmp_path)
    backend.start()
    backend.stop()

    assert calls == [{"cwd": str(tmp_path), "backend": winpty_backend}]


def test_winpty_backend_falls_back_when_winpty_engine_is_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []

    class FakeProcess:
        def isalive(self) -> bool:
            return False

        def read(self) -> str:
            raise EOFError

    class FakePtyProcess:
        @staticmethod
        def spawn(_argv, **kwargs):
            calls.append(kwargs)
            if "backend" in kwargs:
                raise RuntimeError("backend unavailable")
            return FakeProcess()

    winpty_backend = object()
    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            Backend=SimpleNamespace(WinPTY=winpty_backend),
            PtyProcess=FakePtyProcess,
        ),
    )

    backend = WinPtyBackend(initial_directory=tmp_path)
    backend.start()

    assert calls == [
        {"cwd": str(tmp_path), "backend": winpty_backend},
        {"cwd": str(tmp_path)},
    ]


def test_winpty_backend_uses_sendintr_for_interrupt(monkeypatch, tmp_path: Path) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.interrupts = 0
            self.writes: list[str] = []

        def isalive(self) -> bool:
            return True

        def sendintr(self) -> None:
            self.interrupts += 1

        def write(self, text: str) -> None:
            self.writes.append(text)

    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            Backend=SimpleNamespace(WinPTY=object()),
            PtyProcess=SimpleNamespace(),
        ),
    )

    process = FakeProcess()
    backend = WinPtyBackend(initial_directory=tmp_path)
    backend._process = process

    backend.interrupt_current_program()

    assert process.interrupts == 1
    assert process.writes == []


def test_qprocess_backend_kills_windows_process_tree_for_interrupt(monkeypatch) -> None:
    calls: list[object] = []

    class FakeSignal:
        def emit(self, text: str) -> None:
            calls.append(("emit", text))

    class FakeProcess:
        def processId(self) -> int:
            return 1234

        def waitForFinished(self, timeout: int) -> None:
            calls.append(("wait", timeout))

    def fake_run(args, **_kwargs):
        calls.append(("run", args))

    backend = SimpleNamespace(
        process=FakeProcess(),
        output_received=FakeSignal(),
        is_running=lambda: True,
        start=lambda: calls.append("start"),
        write_bytes=lambda data: calls.append(("write", data)),
    )
    backend._kill_windows_process_tree = lambda: QProcessBackend._kill_windows_process_tree(backend)
    monkeypatch.setattr("multipane_commander.terminal.backends.is_windows", lambda: True)
    monkeypatch.setattr("multipane_commander.terminal.backends.subprocess.run", fake_run)

    QProcessBackend.interrupt_current_program(backend)

    assert ("run", ["taskkill", "/PID", "1234", "/T", "/F"]) in calls
    assert ("wait", 2000) in calls
    assert any(call[0] == "emit" for call in calls if isinstance(call, tuple))
    assert "start" in calls
    assert ("write", b"\x03") not in calls


def test_qprocess_backend_force_restarts_without_process_id(monkeypatch) -> None:
    calls: list[object] = []

    class FakeSignal:
        def emit(self, text: str) -> None:
            calls.append(("emit", text))

    class FakeProcess:
        def processId(self) -> int:
            return 0

    backend = SimpleNamespace(
        process=FakeProcess(),
        output_received=FakeSignal(),
        is_running=lambda: True,
        stop=lambda: calls.append("stop"),
        start=lambda: calls.append("start"),
        write_bytes=lambda data: calls.append(("write", data)),
    )
    backend._kill_windows_process_tree = lambda: QProcessBackend._kill_windows_process_tree(backend)
    monkeypatch.setattr("multipane_commander.terminal.backends.is_windows", lambda: True)

    QProcessBackend.interrupt_current_program(backend)

    assert "stop" in calls
    assert "start" in calls
    assert ("write", b"\x03") not in calls


def test_winpty_backend_force_kill_restarts_shell(monkeypatch, tmp_path: Path) -> None:
    calls: list[object] = []

    class FakeSignal:
        def emit(self, text: str) -> None:
            calls.append(("emit", text))

    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            Backend=SimpleNamespace(WinPTY=object()),
            PtyProcess=SimpleNamespace(),
        ),
    )

    backend = WinPtyBackend(initial_directory=tmp_path)
    backend.output_received = FakeSignal()
    backend.stop = lambda: calls.append("stop")
    backend.start = lambda: calls.append("start")

    backend.force_kill_current_program()

    assert calls[0] == "stop"
    assert any(call[0] == "emit" for call in calls if isinstance(call, tuple))
    assert calls[-1] == "start"
