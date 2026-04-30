from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal


class BookmarkStore(QObject):
    bookmarks_changed = Signal(object)

    def __init__(self, initial_paths: list[Path] | None = None) -> None:
        super().__init__()
        self._bookmarks: list[Path] = []
        for path in initial_paths or []:
            self.add(path, emit=False)

    def bookmarks(self) -> list[Path]:
        return list(self._bookmarks)

    def is_bookmarked(self, path: Path) -> bool:
        normalized = path.expanduser()
        return normalized in self._bookmarks

    def add(self, path: Path, *, emit: bool = True) -> None:
        normalized = path.expanduser()
        if normalized in self._bookmarks:
            return
        self._bookmarks.append(normalized)
        if emit:
            self.bookmarks_changed.emit(self.bookmarks())

    def remove(self, path: Path) -> None:
        normalized = path.expanduser()
        if normalized not in self._bookmarks:
            return
        self._bookmarks.remove(normalized)
        self.bookmarks_changed.emit(self.bookmarks())

    def toggle(self, path: Path) -> None:
        normalized = path.expanduser()
        if normalized in self._bookmarks:
            self.remove(normalized)
            return
        self.add(normalized)
