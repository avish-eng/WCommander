from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class EntryInfo:
    name: str
    path: Path
    is_dir: bool
    size: int
    extension: str
    modified_at: datetime
