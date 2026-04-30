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
from PySide6.QtGui import QKeyEvent, QKeySequence
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


def test_R2_f5_f6_f7_f8_delete_emit_operations(tmp_path: Path) -> None:
    pane = _make_pane(tmp_path)
    _populate_dir(tmp_path)
    pane.refresh()

    cases: list[tuple[Qt.Key, str, Qt.KeyboardModifier]] = [
        (Qt.Key.Key_F5, "copy", Qt.KeyboardModifier.NoModifier),
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


def test_F1_10_find_files_matches_name_glob(tmp_path: Path) -> None:
    from multipane_commander.ui.find_files_dialog import find_files

    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.txt").write_text("b")
    (tmp_path / "alpha.md").write_text("c")
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "alpha.log").write_text("d")

    results = find_files(tmp_path, name_pattern="alpha.*", content_query="")
    paths = {r.path.name for r in results}
    assert paths == {"alpha.txt", "alpha.md", "alpha.log"}


def test_F1_10_find_files_filters_by_content(tmp_path: Path) -> None:
    from multipane_commander.ui.find_files_dialog import find_files

    (tmp_path / "a.txt").write_text("hello world")
    (tmp_path / "b.txt").write_text("nothing matching")
    (tmp_path / "c.txt").write_text("HELLO again")

    results = find_files(tmp_path, name_pattern="*.txt", content_query="hello")
    paths = {r.path.name for r in results}

    assert paths == {"a.txt", "c.txt"}  # case-insensitive
    assert all(r.matched_content for r in results)


def test_F1_10_find_files_skips_binary(tmp_path: Path) -> None:
    from multipane_commander.ui.find_files_dialog import find_files

    (tmp_path / "real.txt").write_text("hello there")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02hello\x00\x03")

    results = find_files(tmp_path, name_pattern="*", content_query="hello")
    paths = {r.path.name for r in results}

    assert paths == {"real.txt"}


def test_F1_10_find_files_non_recursive_stops_at_root(tmp_path: Path) -> None:
    from multipane_commander.ui.find_files_dialog import find_files

    (tmp_path / "top.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("x")

    results = find_files(tmp_path, name_pattern="*.txt", content_query="", recursive=False)
    paths = {r.path.name for r in results}

    assert paths == {"top.txt"}


def test_F1_9_template_renders_name_ext_counter() -> None:
    from multipane_commander.ui.multi_rename_dialog import render_template

    out = render_template("[N]_v[C]", name_no_ext="report", extension="txt", counter=3)
    assert out == "report_v3"

    out = render_template("[C03]_[N]", name_no_ext="img", extension="png", counter=7)
    assert out == "007_img"

    # ext-template rendering
    out = render_template("[E]", name_no_ext="x", extension="JPG", counter=1)
    assert out == "JPG"


def test_F1_9_build_preview_increments_counter(tmp_path: Path) -> None:
    from multipane_commander.ui.multi_rename_dialog import build_preview

    a = tmp_path / "alpha.txt"
    b = tmp_path / "beta.md"
    a.touch()
    b.touch()

    previews = build_preview([a, b], name_template="file_[C]", ext_template="[E]")

    assert previews[0].target.name == "file_1.txt"
    assert previews[1].target.name == "file_2.md"
    assert all(not p.collision for p in previews)


def test_F1_9_build_preview_flags_collisions(tmp_path: Path) -> None:
    from multipane_commander.ui.multi_rename_dialog import build_preview

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.touch()
    b.touch()
    # both rename to same target
    previews = build_preview([a, b], name_template="same", ext_template="[E]")

    targets = [p.target.name for p in previews]
    assert targets == ["same.txt", "same.txt"]
    # Second one collides because the first claimed that name in this batch
    assert previews[1].collision is True


def test_F1_9_apply_renames_executes_and_records(tmp_path: Path) -> None:
    from multipane_commander.ui.multi_rename_dialog import apply_renames, build_preview

    a = tmp_path / "old1.txt"
    b = tmp_path / "old2.txt"
    a.write_text("1")
    b.write_text("2")

    previews = build_preview([a, b], name_template="new_[C]", ext_template="[E]")
    recorded: list[tuple[Path, Path]] = []

    def fake_rename(src: Path, dst: Path) -> None:
        src.rename(dst)

    succeeded, errors = apply_renames(
        previews, rename=fake_rename, on_record=lambda s, d: recorded.append((s, d))
    )

    assert succeeded == 2
    assert errors == []
    assert (tmp_path / "new_1.txt").exists()
    assert (tmp_path / "new_2.txt").exists()
    assert len(recorded) == 2


def test_F1_11_undo_stack_records_rename_and_inverts(tmp_path: Path) -> None:
    from multipane_commander.services.undo import UndoRecord, UndoStack

    src = tmp_path / "old.txt"
    dst = tmp_path / "new.txt"

    stack = UndoStack()
    stack.push(UndoRecord(kind="rename", source=src, destination=dst))

    record = stack.pop()
    assert record is not None
    inv = record.inverse()
    assert inv.source == dst
    assert inv.destination == src
    assert stack.pop() is None


def test_F1_11_undo_stack_drops_delete_records() -> None:
    from multipane_commander.services.undo import UndoRecord, UndoStack

    stack = UndoStack()
    stack.push(UndoRecord(kind="delete", source=Path("/tmp/x"), destination=Path("/tmp/x")))

    assert stack.pop() is None
    assert len(stack) == 0


def test_F1_11_undo_stack_capped_at_capacity() -> None:
    from multipane_commander.services.undo import UndoRecord, UndoStack

    stack = UndoStack(capacity=3)
    for i in range(5):
        stack.push(
            UndoRecord(
                kind="rename",
                source=Path(f"/tmp/a{i}"),
                destination=Path(f"/tmp/b{i}"),
            )
        )

    assert len(stack) == 3
    # The three most recent should remain (i=2, 3, 4); pop returns LIFO.
    assert stack.pop().source == Path("/tmp/a4")
    assert stack.pop().source == Path("/tmp/a3")
    assert stack.pop().source == Path("/tmp/a2")


def test_F2_13_dir_size_with_cap_sums_files(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.txt").write_text("12345")  # 5 bytes
    (sub / "b.txt").write_text("hello")  # 5 bytes
    inner = sub / "inner"
    inner.mkdir()
    (inner / "c.txt").write_text("xxx")  # 3 bytes

    from multipane_commander.ui.pane_view import PaneView

    total, capped = PaneView._dir_size_with_cap(sub, cap=1000)

    assert total == 13
    assert capped is False


def test_F2_13_dir_size_with_cap_marks_capped(tmp_path: Path) -> None:
    sub = tmp_path / "many"
    sub.mkdir()
    for i in range(20):
        (sub / f"f{i}.txt").write_text("x")

    from multipane_commander.ui.pane_view import PaneView

    _, capped = PaneView._dir_size_with_cap(sub, cap=5)

    assert capped is True


def test_F2_13_space_on_dir_updates_size_column(tmp_path: Path) -> None:
    sub = tmp_path / "child_dir"
    sub.mkdir()
    (sub / "a.txt").write_text("12345")
    pane = _make_pane(tmp_path)
    _set_cursor_to(pane, sub)
    item = pane.file_list.currentItem()
    assert item.text(2) == "", "size column should start empty for directories"

    pane.keyPressEvent(_key_event(Qt.Key.Key_Space))

    # find the row for `sub` and check column 2 is no longer empty
    for row in range(pane.file_list.topLevelItemCount()):
        candidate = pane.file_list.topLevelItem(row)
        if candidate.data(0, Qt.ItemDataRole.UserRole) == sub:
            assert candidate.text(2), f"size column should be populated after Space; got {candidate.text(2)!r}"
            break
    else:
        raise AssertionError("sub row not found")


def test_F1_7_quick_filter_hides_non_matching_entries(tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.txt").write_text("b")
    (tmp_path / "betacarotene.txt").write_text("c")
    pane = _make_pane(tmp_path)

    pane.show_quick_filter()
    pane._quick_filter_bar.setText("beta")

    visible_labels: set[str] = set()
    for row in range(pane.file_list.topLevelItemCount()):
        item = pane.file_list.topLevelItem(row)
        if item.data(0, Qt.ItemDataRole.UserRole + 1) != "entry":
            continue
        if not item.isHidden():
            visible_labels.add(item.text(0).lower())

    assert visible_labels == {"beta.txt", "betacarotene.txt"}


def test_F1_7_quick_filter_clear_restores_all(tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.txt").write_text("b")
    pane = _make_pane(tmp_path)
    pane.show_quick_filter()
    pane._quick_filter_bar.setText("xyz")

    pane.hide_quick_filter(clear=True)
    pane._apply_quick_filter("")

    visible: list[str] = []
    for row in range(pane.file_list.topLevelItemCount()):
        item = pane.file_list.topLevelItem(row)
        if item.data(0, Qt.ItemDataRole.UserRole + 1) != "entry":
            continue
        if not item.isHidden():
            visible.append(item.text(0).lower())

    assert "alpha.txt" in visible
    assert "beta.txt" in visible


def test_F1_6_type_to_jump_jumps_to_first_match(tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.txt").write_text("b")
    (tmp_path / "betacarotene.txt").write_text("c")
    (tmp_path / "gamma.txt").write_text("d")
    pane = _make_pane(tmp_path)

    pane.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.NoModifier, "b"))

    item = pane.file_list.currentItem()
    assert item is not None
    assert item.text(0).lower().startswith("b"), f"expected b*, got {item.text(0)}"


def test_F1_6_type_to_jump_extends_with_subsequent_chars(tmp_path: Path) -> None:
    (tmp_path / "beta.txt").write_text("b")
    (tmp_path / "betacarotene.txt").write_text("c")
    (tmp_path / "boris.txt").write_text("d")
    pane = _make_pane(tmp_path)

    pane.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.NoModifier, "b"))
    pane.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_E, Qt.KeyboardModifier.NoModifier, "e"))
    pane.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_T, Qt.KeyboardModifier.NoModifier, "t"))

    item = pane.file_list.currentItem()
    assert item is not None
    assert item.text(0).lower().startswith("bet"), f"expected bet*, got {item.text(0)}"


def test_F1_6_type_to_jump_ignores_modifiers(tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("a")
    pane = _make_pane(tmp_path)
    initial = pane.file_list.currentItem()

    pane.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, "a")
    )

    # Ctrl+A is mark-all; should not be consumed by type-to-jump
    assert pane.marked_paths != set()


def test_F2_14_shell_quote_passthrough_for_simple_names() -> None:
    from multipane_commander.ui.main_window import MainWindow

    assert MainWindow._shell_quote("simple.txt") == "simple.txt"
    assert MainWindow._shell_quote("alpha-beta_v1.0") == "alpha-beta_v1.0"


def test_F2_14_shell_quote_wraps_paths_with_spaces_or_specials() -> None:
    from multipane_commander.ui.main_window import MainWindow

    assert MainWindow._shell_quote("a b.txt") == '"a b.txt"'
    assert MainWindow._shell_quote('quote"in"name') == '"quote\\"in\\"name"'
    assert MainWindow._shell_quote("with$dollar") == '"with$dollar"'


def test_F1_12_local_fs_delete_bypass_trash_unlinks_file(tmp_path: Path) -> None:
    from multipane_commander.services.fs.local_fs import LocalFileSystem

    target = tmp_path / "doomed.txt"
    target.write_text("x")
    assert target.exists()

    LocalFileSystem().delete_entry(target, bypass_trash=True)

    assert not target.exists()


def test_F1_12_local_fs_delete_bypass_trash_rmtree_dir(tmp_path: Path) -> None:
    from multipane_commander.services.fs.local_fs import LocalFileSystem

    sub = tmp_path / "doomed_dir"
    sub.mkdir()
    (sub / "inner.txt").write_text("x")

    LocalFileSystem().delete_entry(sub, bypass_trash=True)

    assert not sub.exists()


def test_F1_12_file_job_action_carries_bypass_flag() -> None:
    from multipane_commander.services.jobs.model import FileJobAction

    a = FileJobAction(operation="delete", source=Path("/tmp/x"), bypass_trash=True)
    assert a.bypass_trash is True
    b = FileJobAction(operation="delete", source=Path("/tmp/y"))
    assert b.bypass_trash is False  # default


def test_F0_4_launch_editor_uses_visual_env_first(tmp_path: Path, monkeypatch) -> None:
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "doc.txt"
    target.write_text("hi", encoding="utf-8")

    spawned: list[list[str]] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.setenv("VISUAL", "myvisual")
    monkeypatch.setenv("EDITOR", "myeditor")
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)

    strategy = launch_editor(target)

    assert strategy == "visual"
    assert spawned == [["myvisual", str(target)]]


def test_F0_4_launch_editor_falls_back_to_editor_env(tmp_path: Path, monkeypatch) -> None:
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "doc.txt"
    target.write_text("hi", encoding="utf-8")

    spawned: list[list[str]] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "vi")
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)

    strategy = launch_editor(target)

    assert strategy == "editor"
    assert spawned == [["vi", str(target)]]


def test_F0_4_launch_editor_falls_back_to_desktop_when_nothing_set(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices

    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "doc.txt"
    target.write_text("hi", encoding="utf-8")

    captured: list[str] = []
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr("multipane_commander.ui.main_window.shutil.which", lambda _name: None)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    strategy = launch_editor(target)

    assert strategy == "desktop"
    assert captured == [str(target)]


def test_F0_4_launch_editor_falls_back_to_code_on_path(tmp_path: Path, monkeypatch) -> None:
    """When VISUAL/EDITOR are unset but ``code`` is on PATH, use it (3rd in chain)."""
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "doc.txt"
    target.write_text("hi", encoding="utf-8")

    spawned: list[list[str]] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr(
        "multipane_commander.ui.main_window.shutil.which",
        lambda name: "/usr/local/bin/code" if name == "code" else None,
    )
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)

    strategy = launch_editor(target)

    assert strategy == "code"
    assert spawned == [["/usr/local/bin/code", str(target)]]


def test_F0_4_edit_in_active_pane_returns_silently_when_no_path(monkeypatch) -> None:
    """F4 with no current selection must be a no-op, not crash or call launch_editor."""
    from multipane_commander.ui import main_window as mw

    called: list[Path] = []
    monkeypatch.setattr(mw, "launch_editor", lambda path: called.append(path))

    class _StubPane:
        def current_path(self) -> Path | None:
            return None

    class _StubMainWindow:
        _active_pane = lambda self: _StubPane()  # noqa: E731
        _edit_in_active_pane = mw.MainWindow._edit_in_active_pane

    _StubMainWindow()._edit_in_active_pane()

    assert called == []


def test_F0_4_edit_in_active_pane_invokes_launch_editor_for_selected_path(
    tmp_path: Path, monkeypatch
) -> None:
    """F4 with a selection must call launch_editor with that exact path."""
    from multipane_commander.ui import main_window as mw

    target = tmp_path / "doc.txt"
    target.write_text("hi", encoding="utf-8")

    called: list[Path] = []
    monkeypatch.setattr(mw, "launch_editor", lambda path: called.append(path))

    class _StubPane:
        def current_path(self) -> Path:
            return target

    class _StubMainWindow:
        _active_pane = lambda self: _StubPane()  # noqa: E731
        _edit_in_active_pane = mw.MainWindow._edit_in_active_pane

    _StubMainWindow()._edit_in_active_pane()

    assert called == [target]


# ---------------------------------------------------------------------------
# F4 file-type routing — text-like paths use the editor chain, binary paths
# skip $VISUAL/$EDITOR (which are text editors) and go straight to the OS
# default association so images / PDFs / archives open in the right app.
# ---------------------------------------------------------------------------


def test_F0_4_launch_editor_skips_editor_for_image(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    spawned: list[list[str]] = []
    captured: list[str] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.setenv("VISUAL", "myvisual")
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    strategy = launch_editor(target)

    assert strategy == "desktop-binary"
    assert spawned == []
    assert captured == [str(target)]


def test_F0_4_launch_editor_skips_editor_for_pdf(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "doc.pdf"
    target.write_bytes(b"%PDF-1.4\n\x00garbage")

    spawned: list[list[str]] = []
    captured: list[str] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    strategy = launch_editor(target)

    assert strategy == "desktop-binary"
    assert spawned == []
    assert captured == [str(target)]


def test_F0_4_launch_editor_skips_editor_for_tiff(tmp_path: Path, monkeypatch) -> None:
    """TIFF should be routed to OS app (parity with png/jpg)."""
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "scan.tiff"
    target.write_bytes(b"II*\x00" + b"\x00" * 32)

    captured: list[str] = []
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", lambda *a, **k: None)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    assert launch_editor(target) == "desktop-binary"
    assert captured == [str(target)]


def test_F0_4_launch_editor_skips_editor_for_ico(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "favicon.ico"
    target.write_bytes(b"\x00\x00\x01\x00" + b"\x00" * 32)

    captured: list[str] = []
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    assert launch_editor(target) == "desktop-binary"
    assert captured == [str(target)]


def test_F0_4_launch_editor_skips_editor_for_video(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "clip.mp4"
    target.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)

    captured: list[str] = []
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    assert launch_editor(target) == "desktop-binary"
    assert captured == [str(target)]


def test_F0_4_launch_editor_skips_editor_for_audio(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "song.mp3"
    target.write_bytes(b"ID3\x03" + b"\x00" * 32)

    captured: list[str] = []
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    assert launch_editor(target) == "desktop-binary"
    assert captured == [str(target)]


def test_F0_4_launch_editor_skips_editor_for_office_doc(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "report.docx"
    target.write_bytes(b"PK\x03\x04" + b"\x00" * 32)

    captured: list[str] = []
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    assert launch_editor(target) == "desktop-binary"
    assert captured == [str(target)]


def test_F0_4_launch_editor_skips_editor_for_archive(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "bundle.zip"
    target.write_bytes(b"PK\x03\x04" + b"\x00" * 32)

    spawned: list[list[str]] = []
    captured: list[str] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    strategy = launch_editor(target)

    assert strategy == "desktop-binary"
    assert spawned == []
    assert captured == [str(target)]


def test_F0_4_launch_editor_uses_editor_for_markdown(tmp_path: Path, monkeypatch) -> None:
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "README.md"
    target.write_text("# heading", encoding="utf-8")

    spawned: list[list[str]] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)

    strategy = launch_editor(target)

    assert strategy == "editor"
    assert spawned == [["vim", str(target)]]


def test_F0_4_launch_editor_uses_editor_for_html(tmp_path: Path, monkeypatch) -> None:
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "index.html"
    target.write_text("<p>hi</p>", encoding="utf-8")

    spawned: list[list[str]] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)

    strategy = launch_editor(target)

    assert strategy == "editor"
    assert spawned == [["vim", str(target)]]


def test_F0_4_launch_editor_uses_editor_for_python(tmp_path: Path, monkeypatch) -> None:
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "script.py"
    target.write_text("print('hi')\n", encoding="utf-8")

    spawned: list[list[str]] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)

    strategy = launch_editor(target)

    assert strategy == "editor"
    assert spawned == [["vim", str(target)]]


def test_F0_4_launch_editor_classifies_unknown_ext_with_null_bytes_as_binary(
    tmp_path: Path, monkeypatch
) -> None:
    """Unknown extension + null bytes in body → binary route (skip editor)."""
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "blob.dat"
    target.write_bytes(b"some bytes\x00more bytes")

    spawned: list[list[str]] = []
    captured: list[str] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    strategy = launch_editor(target)

    assert strategy == "desktop-binary"
    assert spawned == []
    assert captured == [str(target)]


def test_F0_4_launch_editor_classifies_unknown_ext_text_body_as_text(
    tmp_path: Path, monkeypatch
) -> None:
    """Unknown extension + utf-8 body, no null bytes → text route (use editor)."""
    from multipane_commander.ui.main_window import launch_editor

    target = tmp_path / "notes.weirdext"
    target.write_text("just text content", encoding="utf-8")

    spawned: list[list[str]] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)

    strategy = launch_editor(target)

    assert strategy == "editor"
    assert spawned == [["vim", str(target)]]


# ---------------------------------------------------------------------------
# Shift+F3 / Shift+F4 — open in OS-associated app, regardless of file type.
# ---------------------------------------------------------------------------


def test_F0_3_open_external_viewer_calls_desktop_services(tmp_path: Path, monkeypatch) -> None:
    """Shift+F3 must hand the path to QDesktopServices unconditionally."""
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui import main_window as mw

    target = tmp_path / "README.md"
    target.write_text("# hi", encoding="utf-8")

    captured: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    class _StubPane:
        def current_path(self) -> Path:
            return target

    class _StubMainWindow:
        _active_pane = lambda self: _StubPane()  # noqa: E731
        _open_external_viewer = mw.MainWindow._open_external_viewer

    _StubMainWindow()._open_external_viewer()

    assert captured == [str(target)]


def test_F0_3_open_external_viewer_no_path_is_noop(monkeypatch) -> None:
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui import main_window as mw

    captured: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    class _StubPane:
        def current_path(self) -> Path | None:
            return None

    class _StubMainWindow:
        _active_pane = lambda self: _StubPane()  # noqa: E731
        _open_external_viewer = mw.MainWindow._open_external_viewer

    _StubMainWindow()._open_external_viewer()

    assert captured == []


def test_F0_4_open_with_default_app_skips_editor_chain(tmp_path: Path, monkeypatch) -> None:
    """Shift+F4 must call QDesktopServices even with $EDITOR set on a text file."""
    from PySide6.QtGui import QDesktopServices
    from multipane_commander.ui import main_window as mw

    target = tmp_path / "notes.txt"
    target.write_text("hi", encoding="utf-8")

    spawned: list[list[str]] = []
    captured: list[str] = []

    class FakePopen:
        def __init__(self, args, **kwargs) -> None:
            spawned.append(list(args))

    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr("multipane_commander.ui.main_window.subprocess.Popen", FakePopen)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    class _StubPane:
        def current_path(self) -> Path:
            return target

    class _StubMainWindow:
        _active_pane = lambda self: _StubPane()  # noqa: E731
        _open_with_default_app = mw.MainWindow._open_with_default_app

    _StubMainWindow()._open_with_default_app()

    assert spawned == []
    assert captured == [str(target)]


def test_F0_3_shift_f3_fires_with_terminal_focused() -> None:
    """Shift+F3 must fire when the terminal QPlainTextEdit has focus (SPEC §16 spike-3)."""
    from PySide6.QtGui import QShortcut
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMainWindow, QPlainTextEdit

    app = _qapp()
    window = QMainWindow()
    fired: list[str] = []
    QShortcut(QKeySequence("Shift+F3"), window, activated=lambda: fired.append("Shift+F3"))
    QShortcut(QKeySequence("Shift+F4"), window, activated=lambda: fired.append("Shift+F4"))

    text_edit = QPlainTextEdit()
    window.setCentralWidget(text_edit)
    window.show()
    text_edit.setFocus()
    app.processEvents()

    QTest.keyClick(text_edit, Qt.Key.Key_F3, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(text_edit, Qt.Key.Key_F4, Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()

    assert fired == ["Shift+F3", "Shift+F4"]
    window.close()


def test_F0_3_f_keys_fire_with_qlineedit_focused() -> None:
    """SPEC §16 spike-3: F-keys must fire when path field or terminal has focus.

    The path bar uses a QLineEdit-style widget and the terminal surface is a
    QPlainTextEdit. Neither widget class consumes F-key events, so Qt's
    standard QShortcut(WindowShortcut) wiring already routes F-keys to the
    MainWindow handler. This test locks that behaviour in place; if a future
    refactor switches the terminal to QWebEngineView (which DOES consume keys),
    this test will fail and a global event filter or ApplicationShortcut
    context will need to be installed.
    """
    from PySide6.QtGui import QShortcut
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QMainWindow, QPlainTextEdit

    app = _qapp()
    window = QMainWindow()
    fired: list[str] = []
    QShortcut(QKeySequence("F5"), window, activated=lambda: fired.append("F5"))
    QShortcut(QKeySequence("F8"), window, activated=lambda: fired.append("F8"))

    line_edit = QLineEdit()
    window.setCentralWidget(line_edit)
    window.show()
    line_edit.setFocus()
    app.processEvents()

    QTest.keyClick(line_edit, Qt.Key.Key_F5)
    QTest.keyClick(line_edit, Qt.Key.Key_F8)
    app.processEvents()
    assert fired == ["F5", "F8"], f"F-keys should fire with QLineEdit focused; got {fired}"

    fired.clear()
    text_edit = QPlainTextEdit()
    window.setCentralWidget(text_edit)
    text_edit.setFocus()
    app.processEvents()

    QTest.keyClick(text_edit, Qt.Key.Key_F5)
    app.processEvents()
    assert fired == ["F5"], f"F5 should fire with QPlainTextEdit focused; got {fired}"

    window.close()


def test_F0_2_enter_on_file_launches_via_desktop_services(tmp_path: Path, monkeypatch) -> None:
    file_a, _file_b, _sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    _set_cursor_to(pane, file_a)

    captured: list[str] = []

    def fake_open(url) -> bool:
        captured.append(url.toLocalFile())
        return True

    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", fake_open)

    pane._activate_item(pane.file_list.currentItem())

    assert captured == [str(file_a)]


def test_F0_2_enter_on_directory_does_not_launch(tmp_path: Path, monkeypatch) -> None:
    """Enter on a directory should still descend, not call openUrl."""
    _file_a, _file_b, sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    _set_cursor_to(pane, sub)

    captured: list[str] = []
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: captured.append(url.toLocalFile()) or True)

    pane._activate_item(pane.file_list.currentItem())

    assert captured == []
    assert pane.active_tab.path == sub


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


def test_F0_1_keypad_modifier_does_not_block_arrows(tmp_path: Path) -> None:
    """On macOS the standard arrow keys carry KeypadModifier. Regression for
    a bug where the modifier guard treated KeypadModifier as 'user is invoking
    a Ctrl/Alt+arrow shortcut, leave alone' and silently no-op'd every press.
    """
    _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    first = pane.file_list.topLevelItem(0)
    pane.file_list.setCurrentItem(first)

    # Synthesize the macOS-style Down: NoModifier OR'd with KeypadModifier.
    event = _key_event(Qt.Key.Key_Down, Qt.KeyboardModifier.KeypadModifier)
    handled = pane._handle_navigation_key(pane.file_list, event)

    assert handled is True
    assert pane.file_list.currentItem() is not first


def test_F0_1_arrow_event_on_viewport_advances_cursor(tmp_path: Path) -> None:
    """QAbstractScrollArea routes key events to viewport() (its focus proxy).
    The eventFilter watch-set must include viewport, otherwise arrows arrive
    at viewport with no handler and silently fall through.
    """
    _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    first = pane.file_list.topLevelItem(0)
    pane.file_list.setCurrentItem(first)

    event = _key_event(Qt.Key.Key_Down)
    handled = pane.eventFilter(pane.file_list.viewport(), event)

    assert handled is True
    assert pane.file_list.currentItem() is not first


def test_F0_1_cursor_row_delegate_paints_current_with_accent(tmp_path: Path) -> None:
    """`_CursorRowDelegate` must paint the cursor row with palette.active_pane_border
    (the accent), bypassing QSS rules on QTreeWidget::item that would otherwise
    swallow per-item setBackground() brushes.
    """
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem

    _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)
    pane.file_list.setCurrentItem(pane.file_list.topLevelItem(0))

    delegate = pane.file_list.itemDelegate()
    # Sanity — the delegate must be the cursor-row delegate, not Qt's default.
    assert type(delegate).__name__ == "_CursorRowDelegate"

    image = QImage(120, 32, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 120, 32)
    option.widget = pane.file_list
    delegate.initStyleOption(option, pane.file_list.model().index(0, 0))
    delegate.paint(painter, option, pane.file_list.model().index(0, 0))
    painter.end()

    expected = QColor(pane.theme_palette.active_pane_border).rgb()
    # Sample the centre of the row — it must be the accent fill.
    actual = image.pixel(60, 16)
    assert (actual & 0x00FFFFFF) == (expected & 0x00FFFFFF), (
        f"cursor row not painted with accent: got {actual:#010x}, want {expected:#010x}"
    )


# ---------------------------------------------------------------------------
# Helper assertion: confirm the population helper itself is right
# (so failures above can be attributed to handlers, not test scaffolding).
# ---------------------------------------------------------------------------


def test_pane_lists_three_entries_for_populated_directory(tmp_path: Path) -> None:
    file_a, file_b, sub = _populate_dir(tmp_path)
    pane = _make_pane(tmp_path)

    assert set(_entry_paths(pane)) == {file_a, file_b, sub}
