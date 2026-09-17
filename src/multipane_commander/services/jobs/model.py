from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4


@dataclass(slots=True)
class FileJobAction:
    operation: str
    source: Path
    destination: Path | None = None
    replace_existing: bool = False
    bypass_trash: bool = False
    undo_backup: Path | None = None


@dataclass(slots=True)
class FileJobResult:
    completed_actions: int
    processed_actions: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    successful_actions: list[FileJobAction] = field(default_factory=list)


@dataclass(slots=True)
class TransferProgress:
    bytes_done: int = 0
    bytes_total: int = 0
    bytes_per_second: float = 0
    seconds_remaining: float | None = None
    label: str = ""

    @property
    def text(self) -> str:
        def size(value):
            for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
                if value < 1024:
                    return f"{value:.1f} {unit}"
                value /= 1024
            return f"{value:.1f} PiB"

        eta = (
            f" · {self.seconds_remaining:.0f}s remaining"
            if self.seconds_remaining is not None
            else ""
        )
        return (
            f"{self.label} · {size(self.bytes_done)} / {size(self.bytes_total)}"
            f" · {size(self.bytes_per_second)}/s{eta}"
        )


@dataclass(slots=True)
class FileJobSnapshot:
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    title: str = ""
    total_actions: int = 0
    completed_actions: int = 0
    processed_actions: int = 0
    current_label: str = "Queued"
    status: str = "queued"
    errors: list[str] = field(default_factory=list)
    transfer: TransferProgress | None = None

    @property
    def progress_percent(self) -> int:
        if self.total_actions <= 0:
            return 0
        return int((self.processed_actions / self.total_actions) * 100)


@dataclass(slots=True)
class JobLogEntry:
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    timestamp: datetime = field(default_factory=datetime.now)
    operation: str = ""
    title: str = ""
    status: str = "completed"
    completed_actions: int = 0
    total_actions: int = 0
    errors: list[str] = field(default_factory=list)
