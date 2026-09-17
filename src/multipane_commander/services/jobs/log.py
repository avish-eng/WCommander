from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from multipane_commander.services.jobs.model import JobLogEntry

MAX_LOG_ENTRIES = 200


class JobLog(QObject):
    """Session history of finished file operations, newest first."""

    entry_added = Signal(object)
    entries_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[JobLogEntry] = []

    def entries(self) -> list[JobLogEntry]:
        return list(self._entries)

    def add_entry(self, entry: JobLogEntry) -> None:
        self._entries.insert(0, entry)
        del self._entries[MAX_LOG_ENTRIES:]
        self.entry_added.emit(entry)
        self.entries_changed.emit()

    def clear(self) -> None:
        if not self._entries:
            return
        self._entries.clear()
        self.entries_changed.emit()

    def error_count(self) -> int:
        return sum(len(entry.errors) for entry in self._entries)
