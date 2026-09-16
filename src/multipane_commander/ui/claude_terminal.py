from __future__ import annotations

import shutil
import uuid
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from multipane_commander.platform import ShellSpec
from multipane_commander.terminal.deep.backend import DeepTerminalBackend
from multipane_commander.ui.deep_terminal.surface import (
    WEB_TERMINAL_AVAILABLE,
    DeepTerminalSurface,
)

_WC_SESSION_NS = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


def _session_id_for(path: Path) -> str:
    return str(uuid.uuid5(_WC_SESSION_NS, str(path.resolve())))


class _ClaudeProcess(QObject):
    """Claude session type using the same process backend as the shell."""

    output_received = Signal(bytes)
    finished = Signal()
    _MAX_BUFFER_BYTES = 1024 * 1024

    def __init__(self, *, backend_factory=DeepTerminalBackend) -> None:
        super().__init__()
        self._backend_factory = backend_factory
        self.backend = None
        self._starting = False
        self._cols, self._rows = 80, 24
        self._output_buffer = deque()
        self._buffer_bytes = 0

    def start(self, cwd: Path, extra_dirs: list[Path], session_id: str | None = None) -> None:
        if self.is_running():
            return
        claude = shutil.which("claude")
        if not claude:
            self._publish(b"\r\nClaude Code CLI was not found on PATH.\r\n")
            self.finished.emit()
            return
        args = ["--session-id", session_id] if session_id else []
        for directory in extra_dirs:
            args.extend(["--add-dir", str(directory)])
        self.backend = self._backend_factory(
            initial_directory=cwd,
            shell=ShellSpec(program=claude, args=args, kind="raw"),
            prefer_pty=True,
            environment_overrides={"TERM": "xterm-256color", "COLORTERM": "truecolor"},
        )
        self.backend.output_received.connect(self._publish)
        self.backend.started.connect(self._started)
        self.backend.exited.connect(self._exited)
        self.backend.failed.connect(self._failed)
        self.backend.resize(self._cols, self._rows)
        self._starting = True
        self.backend.start()

    def _started(self) -> None:
        self._starting = False

    def _exited(self, _code: int) -> None:
        self._starting = False
        self.finished.emit()

    def _failed(self, message: str) -> None:
        self._publish(("\r\nClaude session could not start: " + message + "\r\n").encode())
        self._starting = False
        self.finished.emit()

    def stop(self) -> None:
        self._starting = False
        if self.backend is not None:
            self.backend.stop()

    def is_running(self) -> bool:
        return self._starting or (self.backend is not None and self.backend.is_running())

    def write_bytes(self, data: bytes) -> None:
        if self.backend is not None:
            self.backend.write_bytes(data)

    def resize(self, cols: int, rows: int) -> None:
        self._cols, self._rows = max(1, cols), max(1, rows)
        if self.backend is not None:
            self.backend.resize(self._cols, self._rows)

    def _publish(self, data: bytes) -> None:
        buffered = data[-self._MAX_BUFFER_BYTES:]
        self._output_buffer.append(buffered)
        self._buffer_bytes += len(buffered)
        while self._buffer_bytes > self._MAX_BUFFER_BYTES:
            self._buffer_bytes -= len(self._output_buffer.popleft())
        self.output_received.emit(data)

    def replay(self, write_fn) -> None:
        for chunk in self._output_buffer:
            write_fn(chunk)


class ClaudeSessionCache(QObject):
    """Per-folder sessions shared by both panes; hiding a view detaches it."""

    def __init__(self, parent: QObject | None = None, *, process_factory=_ClaudeProcess) -> None:
        super().__init__(parent)
        self._process_factory = process_factory
        self._sessions: dict[Path, _ClaudeProcess] = {}

    def _discard(self, key: Path, process: _ClaudeProcess) -> None:
        if self._sessions.get(key) is process:
            self._sessions.pop(key, None)

    def _create(self, cwd: Path, extra_dirs: list[Path], session_id: str | None):
        key = cwd.resolve()
        process = self._process_factory()
        self._sessions[key] = process
        process.finished.connect(lambda: self._discard(key, process))
        process.start(cwd, extra_dirs, session_id=session_id)
        return process

    def get_or_create(self, cwd: Path, extra_dirs: list[Path]) -> _ClaudeProcess:
        key = cwd.resolve()
        process = self._sessions.get(key)
        if process is not None and process.is_running():
            return process
        return self._create(cwd, extra_dirs, _session_id_for(key))

    def force_restart(self, cwd: Path, extra_dirs: list[Path]) -> _ClaudeProcess:
        old = self._sessions.pop(cwd.resolve(), None)
        if old is not None:
            old.stop()
        return self._create(cwd, extra_dirs, None)

    def stop_all(self) -> None:
        for process in list(self._sessions.values()):
            process.stop()
        self._sessions.clear()


class ClaudeTerminalWidget(QFrame):
    """Claude view with the shared offline renderer and raw-byte process stream."""

    def __init__(self, session_cache: ClaudeSessionCache, parent=None, *, surface_factory=None):
        super().__init__(parent)
        self.setObjectName("claudeTerminalWidget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._cache = session_cache
        self._current_cwd = None
        self._current_extra = []
        self._current_process = None
        self._last_size = (80, 24)
        self._cwd_label = QLabel("Claude")
        self._cwd_label.setObjectName("claudeTerminalCwd")
        new_button = QPushButton("New Session")
        new_button.setObjectName("secondaryActionButton")
        new_button.clicked.connect(self._restart)
        header = QHBoxLayout()
        header.addWidget(self._cwd_label, 1)
        header.addWidget(new_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        self.output = None
        if surface_factory is not None or WEB_TERMINAL_AVAILABLE:
            self.output = (surface_factory or DeepTerminalSurface)(self)
            self.output.terminal_resized.connect(self._resize)
            self.output.set_sender(self._send_input)
            layout.addWidget(self.output)
            self.setFocusProxy(self.output)
        else:
            layout.addWidget(QLabel("Claude terminal requires the WebEngine renderer."))

    def _send_input(self, data: bytes) -> None:
        if self._current_process is not None:
            self._current_process.write_bytes(data)

    def _resize(self, cols: int, rows: int) -> None:
        self._last_size = (cols, rows)
        if self._current_process is not None:
            self._current_process.resize(cols, rows)

    def _attach(self, process) -> None:
        if self.output is None or process is self._current_process:
            return
        self.stop_session()
        self.output.clear()
        self._current_process = process
        process.resize(*self._last_size)
        process.output_received.connect(self.output.append_output)
        process.replay(self.output.append_output)
        self.output.focus_input()

    def show_for(self, cwd: Path, extra_dirs: list[Path]) -> None:
        self._current_cwd, self._current_extra = cwd, extra_dirs
        self._cwd_label.setText(f"Claude · {cwd}")
        if self.output is not None:
            self._attach(self._cache.get_or_create(cwd, extra_dirs))

    def stop_session(self) -> None:
        """Detach the pane; cached sessions keep running until explicit restart or app exit."""
        if self._current_process is not None and self.output is not None:
            try:
                self._current_process.output_received.disconnect(self.output.append_output)
            except (RuntimeError, TypeError):
                pass
        self._current_process = None

    def _restart(self) -> None:
        if self._current_cwd is not None and self.output is not None:
            self._attach(self._cache.force_restart(self._current_cwd, self._current_extra))
