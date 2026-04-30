"""Undo stack for reversible file operations.

v1 scope (per SPEC §12):
* `rename` and `move` are recorded and inverted by moving the destination
  back to the source.
* `delete` (to-trash) is **not** recorded yet — restoring from the system
  recycle bin is platform-specific and beyond the v1 cut. The stack
  silently drops delete operations rather than half-implementing them.

The stack is bounded (50 records) per SPEC §12.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class UndoRecord:
    kind: str  # "rename" | "move"
    source: Path
    destination: Path

    def inverse(self) -> "UndoRecord":
        return UndoRecord(kind=self.kind, source=self.destination, destination=self.source)


class UndoStack:
    """Bounded LIFO of reversible operations."""

    def __init__(self, *, capacity: int = 50) -> None:
        self._records: deque[UndoRecord] = deque(maxlen=capacity)

    def push(self, record: UndoRecord) -> None:
        if record.kind not in ("rename", "move"):
            return
        self._records.append(record)

    def pop(self) -> UndoRecord | None:
        if not self._records:
            return None
        return self._records.pop()

    def peek(self) -> UndoRecord | None:
        if not self._records:
            return None
        return self._records[-1]

    def clear(self) -> None:
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)

    def snapshot(self) -> Iterable[UndoRecord]:
        return tuple(self._records)
