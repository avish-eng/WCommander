from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


@dataclass(slots=True)
class FileJobAction:
    operation: str
    source: Path
    destination: Path | None = None
    replace_existing: bool = False
    bypass_trash: bool = False


@dataclass(slots=True)
class FileJobResult:
    completed_actions: int
    processed_actions: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)


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

    @property
    def progress_percent(self) -> int:
        if self.total_actions <= 0:
            return 0
        return int((self.processed_actions / self.total_actions) * 100)
