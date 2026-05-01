from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from multipane_commander.services.bookmarks import BookmarkStore
from multipane_commander.state.model import PaneState, TabState
from multipane_commander.ui.pane_view import PaneView


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def _build_pane(path: Path) -> PaneView:
    _qapp()
    return PaneView(
        PaneState(title="Test", tabs=[TabState(title="Test", path=path)]),
        bookmark_store=BookmarkStore(),
        active=True,
    )


def _entry_names(pane: PaneView) -> list[str]:
    names: list[str] = []
    for row in range(pane.file_list.topLevelItemCount()):
        item = pane.file_list.topLevelItem(row)
        if item.data(0, Qt.ItemDataRole.UserRole + 1) == "entry":
            names.append(item.text(0))
    return names


def test_file_list_header_click_sorts_by_size_and_toggles_direction(tmp_path: Path) -> None:
    (tmp_path / "z-dir").mkdir()
    (tmp_path / "a-dir").mkdir()
    (tmp_path / "big.txt").write_text("1234567890", encoding="utf-8")
    (tmp_path / "small.py").write_text("1", encoding="utf-8")
    (tmp_path / "mid.md").write_text("12345", encoding="utf-8")
    pane = _build_pane(tmp_path)

    pane.file_list.header().sectionClicked.emit(2)

    assert pane.file_list.topLevelItem(0).text(0) == ".."
    assert _entry_names(pane) == ["a-dir", "z-dir", "small.py", "mid.md", "big.txt"]

    pane.file_list.header().sectionClicked.emit(2)

    assert pane.file_list.topLevelItem(0).text(0) == ".."
    assert _entry_names(pane) == ["z-dir", "a-dir", "big.txt", "mid.md", "small.py"]


def test_file_list_header_click_sorts_by_modified_time(tmp_path: Path) -> None:
    old_file = tmp_path / "old.txt"
    new_file = tmp_path / "new.txt"
    old_file.write_text("old", encoding="utf-8")
    new_file.write_text("new", encoding="utf-8")
    os.utime(old_file, (1_700_000_000, 1_700_000_000))
    os.utime(new_file, (1_800_000_000, 1_800_000_000))
    pane = _build_pane(tmp_path)

    pane.file_list.header().sectionClicked.emit(3)

    assert _entry_names(pane) == ["old.txt", "new.txt"]

    pane.file_list.header().sectionClicked.emit(3)

    assert _entry_names(pane) == ["new.txt", "old.txt"]
