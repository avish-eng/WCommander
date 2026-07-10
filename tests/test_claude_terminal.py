from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

from multipane_commander.ui import claude_terminal as ct
from multipane_commander.ui.claude_terminal import _ClaudeProcess


class _FinishedWinPtyProcess:
    def isalive(self) -> bool:
        return False

    def read(self) -> str:
        raise EOFError

    def terminate(self) -> None:
        return None


def _join_reader(process: _ClaudeProcess) -> None:
    reader = process._reader
    if reader is not None:
        reader.join(timeout=1)


def test_claude_process_uses_winpty_on_windows(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    winpty_backend = object()

    class FakePtyProcess:
        @staticmethod
        def spawn(argv, **kwargs):
            calls.append((list(argv), kwargs))
            return _FinishedWinPtyProcess()

    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            Backend=SimpleNamespace(WinPTY=winpty_backend),
            PtyProcess=FakePtyProcess,
        ),
    )
    monkeypatch.setattr(ct.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ct.shutil, "which", lambda _name: r"C:\Tools\claude.cmd")

    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()
    process = _ClaudeProcess()
    process.resize(120, 40)

    process.start(tmp_path, [extra_dir], session_id="session-123")
    _join_reader(process)

    assert len(calls) == 1
    argv, options = calls[0]
    assert argv == [
        r"C:\Tools\claude.cmd",
        "--session-id",
        "session-123",
        "--add-dir",
        str(extra_dir),
    ]
    assert options["cwd"] == str(tmp_path)
    assert options["dimensions"] == (40, 120)
    assert options["backend"] is winpty_backend
    env = options["env"]
    assert isinstance(env, dict)
    assert env["TERM"] == "xterm-256color"
    assert env["COLORTERM"] == "truecolor"


def test_claude_process_falls_back_when_winpty_backend_is_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []
    winpty_backend = object()

    class FakePtyProcess:
        @staticmethod
        def spawn(_argv, **kwargs):
            calls.append(kwargs)
            if "backend" in kwargs:
                raise RuntimeError("backend unavailable")
            return _FinishedWinPtyProcess()

    monkeypatch.setitem(
        sys.modules,
        "winpty",
        SimpleNamespace(
            Backend=SimpleNamespace(WinPTY=winpty_backend),
            PtyProcess=FakePtyProcess,
        ),
    )
    monkeypatch.setattr(ct.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ct.shutil, "which", lambda _name: r"C:\Tools\claude.cmd")

    process = _ClaudeProcess()
    process.start(tmp_path, [], session_id=None)
    _join_reader(process)

    assert len(calls) == 2
    assert calls[0]["backend"] is winpty_backend
    assert "backend" not in calls[1]


def test_claude_process_delegates_input_resize_and_stop_to_winpty() -> None:
    class LiveWinPtyProcess:
        def __init__(self) -> None:
            self.writes: list[str] = []
            self.sizes: list[tuple[int, int]] = []
            self.terminations = 0

        def isalive(self) -> bool:
            return True

        def write(self, text: str) -> None:
            self.writes.append(text)

        def setwinsize(self, rows: int, cols: int) -> None:
            self.sizes.append((rows, cols))

        def terminate(self) -> None:
            self.terminations += 1

    winpty_process = LiveWinPtyProcess()
    process = _ClaudeProcess()
    process._winpty_process = winpty_process

    process.write_bytes("hello".encode())
    process.resize(100, 30)
    process.stop()

    assert winpty_process.writes == ["hello"]
    assert winpty_process.sizes == [(30, 100)]
    assert winpty_process.terminations == 1
    assert process._winpty_process is None
