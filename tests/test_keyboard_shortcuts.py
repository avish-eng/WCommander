"""Regression and feature tests for keyboard shortcuts.

The tests in this file fall into two groups:

* `R*` tests — regression suite covering the keyboard surface that was
  already wired up before this work began (panes, F-key bar, tabs, etc).
  Their job is to catch accidental regressions while we add new bindings.

* `F*` tests — feature tests for new bindings added in the same PR (Up/Down
  cursor nav, Enter-on-file launch, global F-key filter, F4/F10 wiring).

The tests deliberately avoid `build_app_context()` (which talks to the real
user config directory) and instead build widgets with synthetic state so
each test gets a clean tree under `tmp_path`.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
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


def _key_event(key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers)


def _populate_dir(root: Path) -> tuple[Path, Path, Path]:
    """Create a stable layout in `root`: two files and one directory."""
    file_a = root / "alpha.txt"
    file_b = root / "beta.txt"
    sub = root / "child_dir"
    file_a.write_text("a", encoding="utf-8")
    file_b.write_text("b", encoding="utf-8")
    sub.mkdir()
    return file_a, file_b, sub


def _make_pane(path: Path) -> PaneView:
    _qapp()
    state = PaneState(title="Test", tabs=[TabState(title=path.name or "root", path=path)])
    pane = PaneView(state, bookmark_store=BookmarkStore(), active=True)
    pane.refresh()
    return pane


def _entry_paths(pane: PaneView) -> list[Path]:
    paths: list[Path] = []
    for row in range(pane.file_list.topLevelItemCount()):
        item = pane.file_list.topLevelItem(row)
        kind = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if kind != "entry":
            continue
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, Path):
            paths.append(data)
    return paths


def _set_cursor_to(pane: PaneView, path: Path) -> None:
    for row in range(pane.file_list.topLevelItemCount()):
        item = pane.file_list.topLevelItem(row)
        if item.data(0, Qt.ItemDataRole.UserRole) == path:
            pane.file_list.setCurrentItem(item)
            return
    raise AssertionError(f"path {path} not in pane")


# ---------------------------------------------------------------------------
# Regression tests — must keep passing while we add new bindings.
# ---------------------------------------------------------------------------


def test_R1_f2_emits_rename(tmp_path: Path) -> None:
    pane = _make_pane(tmp_path)
    _populate_dir(tmp_path)
    pane.refresh()
    captured: list[str] = []
    pane.operation_requested.connect(captured.append)

    pane.keyPressEvent(_key_event(Qt.Key.Key_F2))

    assert captured == ["rename"]


def test_R1_shift_f6_emits_rename(tmp_path: Path) -> None:
    pane = _make_pane(tmp_path)
    _populate_dir(tmp_path)
    pane.refresh()
    captured: list[str] = []
    pane.operation_requested.connect(captured.append)

    pane.keyPressEvent(_key_event(Qt.Key.Key_F6, Qt.KeyboardModifier.ShiftModifier))

    assert captured == ["rename"]


def test_R2_f6_f7_f8_delete_emit_operations(tmp_path: Path) -> None:
    pane = _make_pane(tmp_path)
    _populate_dir(tmp_path)
    pane.refresh()

    cases: list[tuple[Qt.Key, str, Qt.KeyboardModifier]] = [
        (Qt.Key.Key_F6, "move", Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_F7, "mkdir", Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_F8, "delete", Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_Delete, "delete", Qt.KeyboardModifier.NoModifier),
    ]
    for key, expected, mods in cases:
        captured: list[str] = []
        handler = pane.operation_requested.connect(captured.append)
        pane.keyPressEvent(_key_event(key, mods))
        pane.operation_requested.disconnect(handler)
        assert captured == [expected], f"{key} should emit {expected}, got {captured}"


def test_R2_known_quirk_f5_routes_to_refresh_via_standardkey(tmp_path: Path) -> None:
    """On platforms where ``QKeySequence.StandardKey.Refresh`` includes F5
    (e.g. Windows, and apparently macOS Qt builds), the Refresh branch in
    ``PaneView.keyPressEvent`` runs before the explicit F5-Copy branch and
    swallows the event. This is a P0 bug to fix later (TC convention is
    F5 = Copy), but until then this test locks the current behaviour so
    we notice if it changes accidentally.
    """
    pane = _make_pane(tmp_path)
    _populate_dir(tmp_path)
    pane.refresh()
    captured: list[str] = []
    pane.operation_requested.connect(captured.append)

    pane.keyPressEvent(_key_event(Qt.Key.Key_F5))

    # When this assertion flips to ["copy"], remove this test and add F5 to
    # the regular R2 case list above.
    assert captured == ["refresh"], (
        f"F5 routing changed; current emit: {captured}. "
        "If F5 now emits 'copy', delete this test and add F5 to test_R2_*."
    )


def test_R3_backspace_navigates_to_parent(tmp_path: Path) -> None:
    sub = tmp_path / "deeper"
    sub.mkdir()
    pane = _make_pane(sub)

    pane.keyPressEvent(_key_event(Qt.Key.Key_Backspace))

    assert pane.active_tab.path == tmp_path


def test_R4_insert_toggles_selection(tmp_path: Path) -> None:
    """Insert toggles the cursor item AND advances the cursor (TC behaviour).
    To verify toggling, we reset the cursor between presses.
    """
    file_a, _file_b, _sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    _set_cursor_to(pane, file_a)

    pane.keyPressEvent(_key_event(Qt.Key.Key_Insert))
    assert file_a in pane.marked_paths

    _set_cursor_to(pane, file_a)
    pane.keyPressEvent(_key_event(Qt.Key.Key_Insert))
    assert file_a not in pane.marked_paths


def test_R4_insert_advances_cursor_after_toggle(tmp_path: Path) -> None:
    """TC behaviour: Insert advances the cursor to the next entry."""
    file_a, file_b, _sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    _set_cursor_to(pane, file_a)

    pane.keyPressEvent(_key_event(Qt.Key.Key_Insert))

    new_cursor = pane.file_list.currentItem()
    new_path = new_cursor.data(0, Qt.ItemDataRole.UserRole) if new_cursor else None
    assert new_path != file_a, "cursor should have advanced past file_a"


def test_R4_space_toggles_selection(tmp_path: Path) -> None:
    file_a, _file_b, _sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    _set_cursor_to(pane, file_a)

    pane.keyPressEvent(_key_event(Qt.Key.Key_Space))

    assert file_a in pane.marked_paths


def test_R5_escape_clears_marks(tmp_path: Path) -> None:
    file_a, file_b, _sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    pane.marked_paths = {file_a, file_b}

    pane.keyPressEvent(_key_event(Qt.Key.Key_Escape))

    assert pane.marked_paths == set()


def test_R6_ctrl_a_marks_all_entries(tmp_path: Path) -> None:
    file_a, file_b, sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)

    pane.keyPressEvent(_key_event(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier))

    assert pane.marked_paths == {file_a, file_b, sub}


def test_R12_enter_on_directory_descends(tmp_path: Path) -> None:
    _file_a, _file_b, sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    _set_cursor_to(pane, sub)

    pane._activate_item(pane.file_list.currentItem())

    assert pane.active_tab.path == sub


def test_R13_enter_on_parent_row_navigates_up(tmp_path: Path) -> None:
    sub = tmp_path / "nested"
    sub.mkdir()
    pane = _make_pane(sub)
    parent_row = pane.file_list.topLevelItem(0)
    assert parent_row.text(0) == ".."

    pane._activate_item(parent_row)

    assert pane.active_tab.path == tmp_path


def test_R10_ctrl_r_emits_refresh(tmp_path: Path) -> None:
    pane = _make_pane(tmp_path)
    captured: list[str] = []
    pane.operation_requested.connect(captured.append)

    pane.keyPressEvent(_key_event(Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier))

    assert captured == ["refresh"]


# ---------------------------------------------------------------------------
# Feature tests — new bindings added in this PR.
# ---------------------------------------------------------------------------


def test_F0_1_pane_proxies_focus_to_file_list(tmp_path: Path) -> None:
    pane = _make_pane(tmp_path)

    assert pane.focusProxy() is pane.file_list


def test_F0_1_down_arrow_advances_cursor(tmp_path: Path) -> None:
    file_a, _file_b, _sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    _set_cursor_to(pane, file_a)

    pane.file_list.keyPressEvent(_key_event(Qt.Key.Key_Down))

    new_cursor = pane.file_list.currentItem()
    assert new_cursor is not None
    assert new_cursor.data(0, Qt.ItemDataRole.UserRole) != file_a


def test_F0_1_up_arrow_retreats_cursor(tmp_path: Path) -> None:
    _file_a, file_b, _sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    _set_cursor_to(pane, file_b)

    pane.file_list.keyPressEvent(_key_event(Qt.Key.Key_Up))

    new_cursor = pane.file_list.currentItem()
    assert new_cursor is not None
    assert new_cursor.data(0, Qt.ItemDataRole.UserRole) != file_b


def test_F0_1_home_jumps_to_first(tmp_path: Path) -> None:
    _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    last_row = pane.file_list.topLevelItem(pane.file_list.topLevelItemCount() - 1)
    pane.file_list.setCurrentItem(last_row)

    pane.file_list.keyPressEvent(_key_event(Qt.Key.Key_Home))

    assert pane.file_list.currentItem() is pane.file_list.topLevelItem(0)


def test_F0_1_end_jumps_to_last(tmp_path: Path) -> None:
    _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    pane.file_list.setCurrentItem(pane.file_list.topLevelItem(0))

    pane.file_list.keyPressEvent(_key_event(Qt.Key.Key_End))

    assert pane.file_list.currentItem() is pane.file_list.topLevelItem(
        pane.file_list.topLevelItemCount() - 1
    )


# ---------------------------------------------------------------------------
# Helper assertion: confirm the population helper itself is right
# (so failures above can be attributed to handlers, not test scaffolding).
# ---------------------------------------------------------------------------


def test_pane_lists_three_entries_for_populated_directory(tmp_path: Path) -> None:
    file_a, file_b, sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)

    assert set(_entry_paths(pane)) == {file_a, file_b, sub}
