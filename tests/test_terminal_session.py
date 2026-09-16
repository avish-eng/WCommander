from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import sys

from multipane_commander.terminal.backends import QProcessBackend, WinPtyBackend, create_terminal_backend
from multipane_commander.terminal.backends import _clean_child_path
from multipane_commander.terminal.session import TerminalSession
from multipane_commander.terminal.deep.session import DeepTerminalSession
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

_APP = None

def _qapp():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class FakeBackend(QObject):
    output_received = Signal(bytes)
    started = Signal()
    exited = Signal(int)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.shell = SimpleNamespace(kind="posix")
        self.backend_name = "fake"
        self.is_pty = True
        self.writes = []
        self.running = True

    def start(self):
        self.running = True
        self.started.emit()

    def stop(self):
        self.running = False

    def write_text(self, text):
        self.writes.append(text)

    def write_bytes(self, data):
        self.writes.append(data.decode("utf-8", errors="replace"))

    def interrupt_current_program(self):
        self.writes.append("interrupt")

    def terminate_process_tree(self):
        self.writes.append("terminate")

    def is_running(self):
        return self.running


def test_terminal_session_uses_shared_backend_factory(monkeypatch) -> None:
    _qapp()
    backend = FakeBackend()
    seen = {}
    monkeypatch.setattr(
        "multipane_commander.terminal.deep.session.create_deep_backend",
        lambda **kwargs: seen.update(kwargs) or backend,
    )
    session = TerminalSession(initial_directory=Path.home(), experimental_pty=True)
    assert isinstance(session, DeepTerminalSession)
    assert session.backend is backend
    assert session.backend_name == "fake"
    assert session.shell_kind == "posix"
    assert seen == {"initial_directory": Path.home(), "shell": None, "prefer_pty": True}



def test_clean_child_path_removes_frozen_bundle_dir(tmp_path: Path) -> None:
    frozen_dir = tmp_path / "_internal"
    frozen_qt_dir = frozen_dir / "PySide6"
    pyside_dir = tmp_path / ".venv" / "Lib" / "site-packages" / "PySide6"
    shiboken_dir = tmp_path / ".venv" / "Lib" / "site-packages" / "shiboken6"
    other_dir = tmp_path / "System32"
    value = os.pathsep.join(
        [
            str(frozen_dir),
            str(frozen_qt_dir),
            str(pyside_dir),
            str(shiboken_dir),
            str(other_dir),
        ]
    )

    assert _clean_child_path(value, frozen_dir) == str(other_dir)


def test_frozen_windows_package_honors_experimental_pty(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeWinPtyBackend:
        def __init__(self, *, initial_directory: Path) -> None:
            self.initial_directory = initial_directory

    monkeypatch.setattr("multipane_commander.terminal.backends.is_windows", lambda: True)
    monkeypatch.setattr(
        "multipane_commander.terminal.backends._frozen_bundle_dir",
        lambda: tmp_path / "_internal",
    )
    monkeypatch.setattr("multipane_commander.terminal.backends.WinPtyBackend", FakeWinPtyBackend)

    backend = create_terminal_backend(initial_directory=tmp_path, experimental_pty=True)

    assert isinstance(backend, FakeWinPtyBackend)
    assert backend.initial_directory == tmp_path


def test_terminal_session_defers_directory_follow_until_prompt_and_forwards_raw_output(tmp_path) -> None:
    _qapp()
    backend = FakeBackend()
    session = TerminalSession(initial_directory=tmp_path, backend=backend)
    received = []
    session.output_received.connect(received.append)
    target = tmp_path / "folder"
    session.change_directory(target)
    assert backend.writes == []
    backend.output_received.emit(b"\x1b]133;B\x07")
    assert backend.writes == ["cd -- '" + str(target) + "'\n"]
    raw = b"\x1b[31mraw\xe2\x82"
    backend.output_received.emit(raw)
    backend.output_received.emit(b"\xac")
    assert received == [b"\x1b]133;B\x07", raw, b"\xac"]


def test_terminal_session_uses_carriage_return_for_pty_submit() -> None:
    backend = FakeBackend()
    session = TerminalSession(initial_directory=Path.home(), experimental_pty=True, backend=backend)
    assert session.submit_bytes() == b"\r"


def test_terminal_session_interrupts_current_program() -> None:
    backend = FakeBackend()
    session = TerminalSession(initial_directory=Path.home(), backend=backend)
    session.interrupt_current_program()
    assert backend.writes == ["interrupt"]


def test_terminal_session_force_kill_escalates_after_grace_period(monkeypatch) -> None:
    _qapp()
    backend = FakeBackend()
    callbacks = []
    monkeypatch.setattr("multipane_commander.terminal.deep.session.QTimer.singleShot",
                        lambda delay, callback: callbacks.append((delay, callback)))
    session = TerminalSession(initial_directory=Path.home(), backend=backend)
    session.force_kill_current_program()
    assert backend.writes == ["interrupt"]
    assert callbacks[0][0] > 0
    callbacks[0][1]()
    assert backend.writes == ["interrupt", "terminate"]



def test_winpty_backend_prefers_conpty_engine(monkeypatch, tmp_path: Path) -> None:
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

    conpty_backend = object()
    winpty_backend = object()
    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            Backend=SimpleNamespace(ConPTY=conpty_backend, WinPTY=winpty_backend),
            PtyProcess=FakePtyProcess,
        ),
    )

    backend = WinPtyBackend(initial_directory=tmp_path)
    backend.start()
    backend.stop()

    assert len(calls) == 1
    assert calls[0]["cwd"] == str(tmp_path)
    assert calls[0]["backend"] is conpty_backend
    assert isinstance(calls[0]["env"], dict)
    assert backend.backend_name == "conpty"


def test_winpty_backend_falls_back_when_conpty_engine_is_unavailable(
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
            if kwargs.get("backend") is conpty_backend:
                raise RuntimeError("ConPTY unavailable")
            return FakeProcess()

    conpty_backend = object()
    winpty_backend = object()
    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            Backend=SimpleNamespace(ConPTY=conpty_backend, WinPTY=winpty_backend),
            PtyProcess=FakePtyProcess,
        ),
    )

    backend = WinPtyBackend(initial_directory=tmp_path)
    backend.start()

    assert len(calls) == 2
    assert calls[0]["cwd"] == str(tmp_path)
    assert calls[0]["backend"] is conpty_backend
    assert isinstance(calls[0]["env"], dict)
    assert calls[1]["cwd"] == str(tmp_path)
    assert isinstance(calls[1]["env"], dict)
    assert calls[1]["backend"] is winpty_backend
    assert backend.backend_name == "winpty"


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
