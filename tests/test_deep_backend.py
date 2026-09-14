from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from multipane_commander.platform import ShellSpec, is_windows
from multipane_commander.terminal.deep.backend import (
    DeepTerminalBackend,
    _PosixPtyStrategy,
    _WinPtyStrategy,
)


class FakeStrategy:
    name = "fake-pty"
    is_pty = True

    def __init__(self) -> None:
        self.spawn_args: dict[str, object] | None = None
        self.writes: list[bytes] = []
        self.resizes: list[tuple[int, int]] = []
        self.terminations: list[bool] = []
        self._chunks = [b"hello ", b"world"]
        self._alive = True
        self._process = None

    @property
    def process(self):
        return self._process

    def spawn(self, argv, *, cwd, env, rows, cols) -> None:
        self.spawn_args = {"argv": argv, "cwd": cwd, "env": env, "rows": rows, "cols": cols}

    def read(self) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        self._alive = False
        return b""

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))

    def terminate(self, *, force: bool) -> None:
        self.terminations.append(force)
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    def exit_code(self) -> int:
        return 0


class FailingStrategy(FakeStrategy):
    def spawn(self, argv, *, cwd, env, rows, cols) -> None:
        raise RuntimeError("no pty here")


def _backend(tmp_path: Path, *, prefer_pty: bool = True) -> DeepTerminalBackend:
    shell = ShellSpec(program=sys.executable, args=[], kind="posix")
    return DeepTerminalBackend(
        initial_directory=tmp_path,
        shell=shell,
        prefer_pty=prefer_pty,
    )


def test_backend_prefers_pty_strategies_when_available(tmp_path: Path) -> None:
    backend = _backend(tmp_path, prefer_pty=True)

    names = [factory.__name__ for factory in backend._strategy_factories()]

    expected_pty = "_WinPtyStrategy" if is_windows() else "_PosixPtyStrategy"
    assert names == [expected_pty, "_PipeStrategy"]
    assert backend.backend_name in {"conpty", "posix-pty"}
    assert backend.is_pty is True


def test_backend_can_force_pipe_first(tmp_path: Path) -> None:
    backend = _backend(tmp_path, prefer_pty=False)

    names = [factory.__name__ for factory in backend._strategy_factories()]

    assert names[0] == "_PipeStrategy"
    assert names[1] in {"_WinPtyStrategy", "_PosixPtyStrategy"}
    assert backend.backend_name == "pipe"
    assert backend.is_pty is False


def test_backend_spawns_and_streams_output(tmp_path: Path, monkeypatch) -> None:
    backend = _backend(tmp_path)
    strategy = FakeStrategy()
    monkeypatch.setattr(backend, "_strategy_factories", lambda: [lambda: strategy])
    chunks: list[bytes] = []
    started: list[bool] = []
    exited: list[int] = []
    backend.output_received.connect(chunks.append)
    backend.started.connect(lambda: started.append(True))
    backend.exited.connect(exited.append)

    backend._spawn_worker()

    assert chunks == [b"hello ", b"world"]
    assert started == [True]
    assert exited == [0]
    assert strategy.spawn_args is not None
    assert strategy.spawn_args["cwd"] == str(tmp_path)
    assert strategy.spawn_args["env"]["MPC_TERMINAL"] == "deep"


def test_backend_falls_back_when_first_strategy_fails(tmp_path: Path, monkeypatch) -> None:
    backend = _backend(tmp_path)
    strategy = FakeStrategy()
    monkeypatch.setattr(
        backend,
        "_strategy_factories",
        lambda: [lambda: FailingStrategy(), lambda: strategy],
    )
    failed: list[str] = []
    backend.failed.connect(failed.append)

    backend._spawn_worker()

    assert failed == []
    assert backend.is_running() is False


def test_backend_reports_failure_when_all_strategies_fail(tmp_path: Path, monkeypatch) -> None:
    backend = _backend(tmp_path)
    monkeypatch.setattr(backend, "_strategy_factories", lambda: [lambda: FailingStrategy()])
    failed: list[str] = []
    backend.failed.connect(failed.append)

    backend._spawn_worker()

    assert len(failed) == 1
    assert "no pty here" in failed[0]


def test_backend_flushes_input_queued_before_spawn(tmp_path: Path, monkeypatch) -> None:
    backend = _backend(tmp_path)
    strategy = FakeStrategy()
    monkeypatch.setattr(backend, "_strategy_factories", lambda: [lambda: strategy])
    backend._input_queue.extend(b"queued-command\r")

    backend._spawn_worker()

    assert strategy.writes == [b"queued-command\r"]


def test_backend_writes_and_dedups_resize(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    strategy = FakeStrategy()
    backend._strategy = strategy

    backend.write_bytes(b"ls\r")
    backend.resize(80, 24)
    backend.resize(80, 24)
    backend.resize(120, 40)
    backend.resize(120, 40)

    assert strategy.writes == [b"ls\r"]
    assert strategy.resizes == [(120, 40)]


def test_backend_resize_before_spawn_is_applied_at_spawn(tmp_path: Path, monkeypatch) -> None:
    backend = _backend(tmp_path)
    strategy = FakeStrategy()
    monkeypatch.setattr(backend, "_strategy_factories", lambda: [lambda: strategy])
    backend.resize(132, 43)

    backend._spawn_worker()

    assert strategy.spawn_args is not None
    assert strategy.spawn_args["cols"] == 132
    assert strategy.spawn_args["rows"] == 43


def test_backend_interrupt_uses_ctrl_c_for_pty(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    strategy = FakeStrategy()
    backend._strategy = strategy

    backend.interrupt_current_program()

    assert strategy.writes == [b"\x03"]


def test_backend_interrupt_terminates_pipe_process(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    strategy = FakeStrategy()
    strategy.is_pty = False
    backend._strategy = strategy

    backend.interrupt_current_program()

    assert strategy.terminations == [True]


def test_backend_stop_requests_graceful_termination(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    strategy = FakeStrategy()
    backend._strategy = strategy

    backend.stop()

    assert strategy.terminations == [False]
    assert backend._stop_event.is_set()


def test_backend_force_terminate_after_grace_kills_live_strategy(tmp_path: Path, monkeypatch) -> None:
    backend = _backend(tmp_path)
    strategy = FakeStrategy()
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    backend._force_terminate_after_grace(strategy)

    assert strategy.terminations == [True]


def test_backend_pid_reports_none_without_process(tmp_path: Path) -> None:
    backend = _backend(tmp_path)

    assert backend.pid() is None


@pytest.mark.skipif(is_windows(), reason="POSIX pty strategies are only available on macOS/Linux")
def test_backend_real_posix_pty_streams_output(tmp_path: Path, monkeypatch) -> None:
    shell = ShellSpec(
        program=sys.executable,
        args=["-c", "print('deep-pty-ok')"],
        kind="posix",
    )
    backend = DeepTerminalBackend(initial_directory=tmp_path, shell=shell, prefer_pty=True)
    chunks: list[bytes] = []
    backend.output_received.connect(chunks.append)

    backend._spawn_worker()

    assert b"deep-pty-ok" in b"".join(chunks)


def test_backend_real_pipe_streams_output(tmp_path: Path) -> None:
    shell = ShellSpec(
        program=sys.executable,
        args=["-c", "print('deep-pipe-ok')"],
        kind="posix",
    )
    backend = DeepTerminalBackend(initial_directory=tmp_path, shell=shell, prefer_pty=False)
    chunks: list[bytes] = []
    backend.output_received.connect(chunks.append)

    backend._spawn_worker()

    assert b"deep-pipe-ok" in b"".join(chunks)
    assert backend.backend_name == "pipe"


@pytest.mark.skipif(not is_windows(), reason="ConPTY is Windows-only")
def test_backend_real_winpty_streams_output(tmp_path: Path) -> None:
    shell = ShellSpec(
        program=sys.executable,
        args=["-c", "print('deep-conpty-ok')"],
        kind="posix",
    )
    backend = DeepTerminalBackend(initial_directory=tmp_path, shell=shell, prefer_pty=True)
    chunks: list[bytes] = []
    backend.output_received.connect(chunks.append)

    backend._spawn_worker()

    assert b"deep-conpty-ok" in b"".join(chunks)
    assert backend.backend_name in {"conpty", "winpty", "pipe"}


def test_winpty_strategy_sends_interrupt_via_sendintr(monkeypatch, tmp_path: Path) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.interrupts = 0

        def isalive(self) -> bool:
            return True

        def sendintr(self) -> None:
            self.interrupts += 1

    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            Backend=SimpleNamespace(WinPTY=object()),
            PtyProcess=SimpleNamespace(),
        ),
    )
    strategy = _WinPtyStrategy()
    process = FakeProcess()
    strategy._process = process

    strategy.send_interrupt()

    assert process.interrupts == 1


def test_posix_strategy_terminate_closes_master_fd(tmp_path: Path, monkeypatch) -> None:
    strategy = _PosixPtyStrategy()
    closed: list[int] = []
    monkeypatch.setattr(os, "close", lambda fd: closed.append(fd))

    class FakeProcess:
        def poll(self):
            return 0

    strategy._master_fd = 7
    strategy._process = FakeProcess()

    strategy.terminate(force=True)

    assert closed == [7]
    assert strategy._master_fd is None
