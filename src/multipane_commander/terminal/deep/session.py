from __future__ import annotations

import codecs
import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from multipane_commander.platform import ShellSpec, build_cd_command, shell_line_ending
from multipane_commander.terminal.deep.backend import DeepTerminalBackend, create_deep_backend
from multipane_commander.terminal.deep.shell_integration import ShellIntegrationParser

_FORCE_KILL_GRACE_MS = 1_200
_MAX_SYNC_ATTEMPTS = 3


class DeepTerminalSession(QObject):
    """PTY session with prompt-aware directory following.

    Directory changes are only written when the shell is idle, so navigating
    panes can never type a path into a running program. When the shell emits
    OSC 7 / OSC 9;9 the session learns its real working directory and skips
    redundant `cd` calls entirely; a user who changes directory by hand stays
    in sync instead of silently drifting.
    """

    output_received = Signal(bytes)
    started = Signal()
    exited = Signal(int)
    failed = Signal(str)
    cwd_changed = Signal(object)
    title_changed = Signal(str)
    prompt_changed = Signal(bool)
    command_finished = Signal(int)
    command_detected = Signal(str)

    def __init__(
        self,
        *,
        initial_directory: Path,
        backend: DeepTerminalBackend | None = None,
        parser: ShellIntegrationParser | None = None,
        shell: ShellSpec | None = None,
        prefer_pty: bool = True,
    ) -> None:
        super().__init__()
        self.initial_directory = initial_directory
        self.parser = parser or ShellIntegrationParser()
        self.backend = backend or create_deep_backend(
            initial_directory=initial_directory,
            shell=shell,
            prefer_pty=prefer_pty,
        )
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._desired_directory = initial_directory
        self._known_directory = initial_directory
        self._last_sent_directory = initial_directory
        self._sync_attempts = 0
        self._restart_pending = False
        self._last_prompt = False
        self._last_exit_code: int | None = None
        self._last_command: str | None = None
        self._last_title: str | None = None
        self.backend.output_received.connect(self._read_output)
        self.backend.started.connect(self._handle_started)
        self.backend.exited.connect(self._handle_exited)
        self.backend.failed.connect(self._handle_failed)

    @property
    def shell_kind(self) -> str:
        return self.backend.shell.kind

    @property
    def backend_name(self) -> str:
        return self.backend.backend_name

    @property
    def is_pty(self) -> bool:
        return self.backend.is_pty

    @property
    def desired_directory(self) -> Path:
        return self._desired_directory

    @property
    def known_directory(self) -> Path:
        return self._known_directory

    @property
    def at_prompt(self) -> bool:
        return self.parser.at_prompt

    def start(self) -> None:
        self._restart_pending = False
        self.parser.reset()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._last_prompt = False
        self._last_exit_code = None
        self._last_command = None
        self._last_title = None
        self.backend.initial_directory = self._desired_directory
        self.backend.start()

    def stop(self) -> None:
        self._restart_pending = False
        self.backend.stop()

    def restart(self) -> None:
        self._restart_pending = True
        if self.backend.is_running():
            self.backend.stop()
            return
        self._restart_pending = False
        self.start()

    def is_running(self) -> bool:
        return self.backend.is_running()

    def write_bytes(self, data: bytes) -> None:
        self.parser.note_input(data)
        self.backend.write_bytes(data)

    def write_text(self, text: str) -> None:
        self.write_bytes(text.encode("utf-8", errors="replace"))

    def send_command(self, command: str) -> None:
        cleaned = command.rstrip()
        self.write_bytes(cleaned.encode("utf-8", errors="replace"))
        self.write_bytes(self.submit_bytes())

    def submit_bytes(self) -> bytes:
        if self.backend.is_pty:
            return b"\r"
        return shell_line_ending(self.shell_kind).encode("utf-8")

    def resize(self, cols: int, rows: int) -> None:
        self.backend.resize(cols, rows)

    def interrupt_current_program(self) -> None:
        self.backend.interrupt_current_program()

    def force_kill_current_program(self) -> None:
        self.backend.interrupt_current_program()
        QTimer.singleShot(_FORCE_KILL_GRACE_MS, self._escalate_kill)

    def change_directory(self, path: Path) -> None:
        if path != self._desired_directory:
            self._sync_attempts = 0
        self._desired_directory = path
        self.backend.initial_directory = path
        self._maybe_sync_directory()

    def _escalate_kill(self) -> None:
        if not self.backend.is_running():
            return
        if self.parser.at_prompt:
            return
        self.backend.terminate_process_tree()

    def _maybe_sync_directory(self) -> None:
        if not self.backend.is_running():
            return
        if not self.parser.at_prompt:
            return
        desired = self._desired_directory
        if desired == self._known_directory or desired == self._last_sent_directory:
            return
        if self._sync_attempts >= _MAX_SYNC_ATTEMPTS:
            return
        command = build_cd_command(desired, self.shell_kind)
        self._last_sent_directory = desired
        self._known_directory = desired
        self._sync_attempts += 1
        self.backend.write_text(command + shell_line_ending(self.shell_kind))

    def _read_output(self, data: bytes) -> None:
        text = self._decoder.decode(data)
        if text:
            self.parser.feed(text)
            self._publish_state()
        self.output_received.emit(data)

    def _publish_state(self) -> None:
        parser = self.parser
        if parser.cwd:
            path = self._path_from_shell(parser.cwd)
            if path is not None and path != self._known_directory:
                self._known_directory = path
                self._sync_attempts = 0
                self.cwd_changed.emit(path)
                self._maybe_sync_directory()
        if parser.title and parser.title != self._last_title:
            self._last_title = parser.title
            self.title_changed.emit(parser.title)
        if parser.at_prompt != self._last_prompt:
            self._last_prompt = parser.at_prompt
            self.prompt_changed.emit(parser.at_prompt)
            if parser.at_prompt:
                self._maybe_sync_directory()
        exit_code = parser.state.exit_code
        if exit_code is not None and exit_code != self._last_exit_code:
            self._last_exit_code = exit_code
            self.command_finished.emit(exit_code)
        if parser.state.last_command and parser.state.last_command != self._last_command:
            self._last_command = parser.state.last_command
            self.command_detected.emit(parser.state.last_command)

    def _path_from_shell(self, value: str) -> Path | None:
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return Path(os.path.normpath(cleaned))
        except (OSError, ValueError):
            return None

    def _handle_started(self) -> None:
        self._last_sent_directory = self._desired_directory
        self._known_directory = self._desired_directory
        self.started.emit()

    def _handle_exited(self, exit_code: int) -> None:
        self.exited.emit(exit_code)
        if self._restart_pending:
            self._restart_pending = False
            self.start()

    def _handle_failed(self, message: str) -> None:
        self.failed.emit(message)
