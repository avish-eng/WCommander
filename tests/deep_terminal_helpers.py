from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal


class FakeDeepSession(QObject):
    output_received = Signal(bytes)
    started = Signal()
    exited = Signal(int)
    failed = Signal(str)
    cwd_changed = Signal(object)
    title_changed = Signal(str)
    prompt_changed = Signal(bool)
    command_finished = Signal(int)
    command_detected = Signal(str)

    def __init__(self, initial_directory: Path, prefer_pty: bool = True) -> None:
        super().__init__()
        self.initial_directory = initial_directory
        self.prefer_pty = prefer_pty
        self.backend_name = "conpty"
        self.shell_kind = "pwsh"
        self.is_pty = True
        self.at_prompt = True
        self.known_directory = initial_directory
        self.backend = self
        self._running = False
        self.draft_started_at_prompt = False
        self.starts = 0
        self.stops = 0
        self.restarts = 0
        self.resizes: list[tuple[int, int]] = []
        self.directories: list[Path] = []
        self.interrupts = 0
        self.force_kills = 0
        self.cancelled_directory_changes = 0
        self.commands: list[tuple[str, Path | None, bool]] = []
        self.writes: list[bytes] = []

    @property
    def can_inject(self) -> bool:
        return self._running and self.at_prompt

    def submit_command(self, command: str, *, cwd: Path | None = None, run: bool = True) -> bool:
        if not self.can_inject:
            return False
        self.commands.append((command, cwd, run))
        if run:
            self.command_detected.emit(command)
        return True

    def cancel_directory_change(self) -> None:
        self.cancelled_directory_changes += 1

    def start(self) -> None:
        self.starts += 1
        self._running = True
        self.started.emit()

    def stop(self) -> None:
        self.stops += 1
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def restart(self) -> None:
        self.restarts += 1

    def write_bytes(self, data: bytes) -> None:
        self.writes.append(data)

    def submit_bytes(self) -> bytes:
        return b"\r"

    def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))

    def change_directory(self, path: Path) -> None:
        self.directories.append(path)

    def interrupt_current_program(self) -> None:
        self.interrupts += 1

    def force_kill_current_program(self) -> None:
        self.force_kills += 1
