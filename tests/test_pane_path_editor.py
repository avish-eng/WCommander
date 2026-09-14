from __future__ import annotations

import os
from pathlib import Path

from ui_wait import wait_for_pane

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
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
    pane = PaneView(
        PaneState(title="Test", tabs=[TabState(title="Test", path=path)]),
        bookmark_store=BookmarkStore(),
        active=True,
    )
    wait_for_pane(pane)
    return pane


def _click(pane: PaneView, position: QPoint) -> bool:
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(position),
        QPointF(pane.breadcrumb_host.mapToGlobal(position)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    return pane.eventFilter(pane.breadcrumb_host, event)


def test_clicking_empty_breadcrumb_space_opens_the_path_editor(tmp_path: Path) -> None:
    (tmp_path / "child").mkdir()
    pane = _build_pane(tmp_path)
    pane.resize(900, 600)
    pane.show()
    _qapp().processEvents()

    # The reserved strip just left of the bookmark button, which stays empty
    # even when a deep path fills the rest of the row.
    empty_spot = QPoint(
        pane.bookmark_toggle.geometry().left() - 14,
        pane.breadcrumb_host.height() // 2,
    )
    assert pane.breadcrumb_host.childAt(empty_spot) is None

    assert _click(pane, empty_spot) is True
    assert pane.path_edit_active()
    assert pane.breadcrumb_host.isHidden()
    assert pane.path_editor.text() == str(tmp_path)
    assert pane.path_editor.selectedText() == str(tmp_path)
    assert pane.path_editor.hasFocus()

    pane.close()


def test_clicking_a_breadcrumb_button_does_not_open_the_editor(tmp_path: Path) -> None:
    pane = _build_pane(tmp_path)
    pane.resize(900, 600)
    pane.show()
    _qapp().processEvents()

    on_back_button = pane.back_button.geometry().center()
    assert pane.breadcrumb_host.childAt(on_back_button) is not None

    assert _click(pane, on_back_button) is False
    assert not pane.path_edit_active()

    pane.close()


def test_pressing_the_disabled_back_button_never_opens_the_editor(tmp_path: Path) -> None:
    pane = _build_pane(tmp_path)
    pane.resize(900, 600)
    pane.show()
    _qapp().processEvents()

    # Fresh tab: nothing to go back to, so Qt forwards presses on the dead
    # button (and the gap beside it) up to the breadcrumb host.
    assert not pane.back_button.isEnabled()
    beside_back_button = QPoint(
        pane.back_button.geometry().right() + 1,
        pane.breadcrumb_host.height() // 2,
    )

    assert _click(pane, beside_back_button) is False
    assert not pane.path_edit_active()

    pane.close()


def test_back_button_still_navigates(tmp_path: Path) -> None:
    (tmp_path / "child").mkdir()
    pane = _build_pane(tmp_path)

    pane.navigate_to(tmp_path / "child")
    assert pane.current_directory() == tmp_path / "child"
    assert pane.back_button.isEnabled()

    pane.back_button.click()

    assert pane.current_directory() == tmp_path
    assert not pane.path_edit_active()


def test_path_editor_navigates_to_a_typed_directory(tmp_path: Path) -> None:
    (tmp_path / "child").mkdir()
    pane = _build_pane(tmp_path)

    pane.begin_path_edit()
    pane.path_editor.setText(str(tmp_path / "child"))
    pane._commit_path_edit()

    assert pane.current_directory() == (tmp_path / "child").resolve()
    assert not pane.path_edit_active()
    assert not pane.breadcrumb_host.isHidden()


def test_path_editor_accepts_relative_paths_and_files(tmp_path: Path) -> None:
    (tmp_path / "child").mkdir()
    (tmp_path / "child" / "note.txt").write_text("hi", encoding="utf-8")
    pane = _build_pane(tmp_path)

    pane.begin_path_edit()
    pane.path_editor.setText("child")
    pane._commit_path_edit()
    assert pane.current_directory() == (tmp_path / "child").resolve()

    # A file resolves to the folder containing it.
    pane.begin_path_edit()
    pane.path_editor.setText(str(tmp_path / "child" / "note.txt"))
    pane._commit_path_edit()
    assert pane.current_directory() == (tmp_path / "child").resolve()


def test_path_editor_keeps_editing_on_a_bad_path(tmp_path: Path) -> None:
    pane = _build_pane(tmp_path)

    pane.begin_path_edit()
    pane.path_editor.setText(str(tmp_path / "does-not-exist"))
    pane._commit_path_edit()

    assert pane.path_edit_active()
    assert pane.path_editor.property("invalid") is True
    assert pane.current_directory() == tmp_path

    # Typing clears the error state again.
    pane.path_editor.textEdited.emit("x")
    assert pane.path_editor.property("invalid") is False


def test_escape_cancels_the_path_editor(tmp_path: Path) -> None:
    pane = _build_pane(tmp_path)

    pane.begin_path_edit()
    assert pane.path_edit_active()

    pane.cancel_path_edit()

    assert not pane.path_edit_active()
    assert not pane.breadcrumb_host.isHidden()
    assert pane.current_directory() == tmp_path
