from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from multipane_commander.platform import build_cd_command, shell_line_ending
from multipane_commander.terminal.backends import TerminalBackend, create_terminal_backend


class TerminalSession(QObject):
    output_received = Signal(str)
    started = Signal()

    def __init__(self, *, initial_directory: Path, experimental_pty: bool = False) -> None:
        super().__init__()
        self.initial_directory = initial_directory
        self._last_synced_directory_key = self._path_key(initial_directory)
        self._hidden_commands: list[str] = []
        self.experimental_pty = experimental_pty
        self.backend: TerminalBackend = create_terminal_backend(
            initial_directory=initial_directory,
            experimental_pty=experimental_pty,
        )
        self.backend.output_received.connect(self._read_output)
        self.backend.started.connect(self.started.emit)

    @property
    def shell_kind(self) -> str:
        return self.backend.shell.kind

    @property
    def backend_name(self) -> str:
        return self.backend.backend_name

    def start(self) -> None:
        self._last_synced_directory_key = self._path_key(self.initial_directory)
        self.backend.start()

    def stop(self) -> None:
        self.backend.stop()

    def send_command(self, command: str) -> None:
        self.backend.send_command(command)

    def write_text(self, text: str) -> None:
        self.backend.write_text(text)

    def write_bytes(self, data: bytes) -> None:
        self.backend.write_bytes(data)

    def interrupt_current_program(self) -> None:
        self.backend.interrupt_current_program()

    def force_kill_current_program(self) -> None:
        self.backend.force_kill_current_program()

    def submit_bytes(self) -> bytes:
        if self.backend_name != "qprocess":
            return b"\r"
        return shell_line_ending(self.shell_kind).encode("utf-8")

    def resize(self, cols: int, rows: int) -> None:
        self.backend.resize(cols, rows)

    def change_directory(self, path: Path) -> None:
        path_key = self._path_key(path)
        self.initial_directory = path
        if not self.backend.is_running():
            return
        if path_key == self._last_synced_directory_key:
            return

        command = self._directory_change_command(path)
        self._send_hidden_command(command)
        self._last_synced_directory_key = path_key

    def _directory_change_command(self, path: Path) -> str:
        return build_cd_command(path, self.shell_kind)

    def _read_output(self, data: str) -> None:
        cleaned = self._strip_hidden_commands(data)
        if cleaned:
            self.output_received.emit(cleaned)

    def _path_key(self, path: Path) -> str:
        normalized = path.expanduser()
        return os.path.normcase(os.path.normpath(str(normalized)))

    def _send_hidden_command(self, command: str) -> None:
        self._hidden_commands.append(command)
        self.backend.write_text(command + shell_line_ending(self.shell_kind))

    def _strip_hidden_commands(self, data: str) -> str:
        if not data or not self._hidden_commands:
            return data

        remaining: list[str] = []
        cleaned = data
        for command in self._hidden_commands:
            if command in cleaned:
                cleaned = cleaned.replace(command, "", 1)
            else:
                remaining.append(command)
        self._hidden_commands = remaining
        return cleaned
