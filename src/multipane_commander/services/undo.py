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
from contextlib import contextmanager
import logging

from multipane_commander.services.fs.local_fs import LocalFileSystem


@dataclass(slots=True)
class UndoRecord:
    kind: str  # "rename" | "move"
    source: Path
    destination: Path
    backup: Path | None = None

    def inverse(self) -> "UndoRecord":
        return UndoRecord(kind=self.kind, source=self.destination, destination=self.source)


class UndoStack:
    """Bounded LIFO of reversible operations."""

    def __init__(self, *, capacity: int = 50) -> None:
        self._records: deque[UndoRecord | UndoGroup] = deque(maxlen=capacity)
        self._group: list[UndoRecord] | None = None

    def push(self, record: UndoRecord) -> None:
        if record.kind not in ("rename", "move"):
            return
        if self._group is not None:
            self._group.append(record)
            return
        self._append(record)

    def _append(self, entry):
        if self._records and len(self._records) == self._records.maxlen:
            self._release_backups(self._records[0])
        self._records.append(entry)

    @staticmethod
    def _release_backups(entry):
        records = entry.records if isinstance(entry, UndoGroup) else [entry]
        for record in records:
            if record.backup is not None and record.backup.exists():
                try:
                    LocalFileSystem().remove_existing(record.backup)
                except OSError:
                    logging.getLogger(__name__).warning(
                        "Could not remove expired undo backup %s", record.backup, exc_info=True
                    )

    @contextmanager
    def group(self):
        records: list[UndoRecord] = []
        if self._group is not None:
            raise RuntimeError("Nested undo groups are unsupported")
        self._group = records
        try:
            yield
        finally:
            self._group = None
            if records:
                self._append(UndoGroup(records))

    def undo(self, fs: LocalFileSystem) -> bool:
        entry = self.peek()
        if entry is None:
            return False
        records = entry.records if isinstance(entry, UndoGroup) else [entry]
        while records:
            record = records[-1]
            if not record.destination.exists() and not record.destination.is_symlink():
                raise FileNotFoundError(f"Cannot undo: {record.destination} no longer exists")
            if record.source.exists() or record.source.is_symlink():
                raise FileExistsError(f"Cannot undo: {record.source} now exists")
            fs.replace_entry(
                record.destination, record.source, operation="move", replace_existing=False
            )
            if record.backup is not None:
                try:
                    fs.move_entry(record.backup, record.destination)
                except OSError:
                    fs.move_entry(record.source, record.destination)
                    raise
            records.pop()
        self.pop()
        return True

    def pop(self) -> UndoRecord | UndoGroup | None:
        if not self._records:
            return None
        return self._records.pop()

    def peek(self) -> UndoRecord | UndoGroup | None:
        if not self._records:
            return None
        return self._records[-1]

    def clear(self) -> None:
        for record in self._records:
            self._release_backups(record)
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)

    def snapshot(self) -> Iterable[UndoRecord | UndoGroup]:
        return tuple(self._records)


@dataclass(slots=True)
class UndoGroup:
    records: list[UndoRecord]
