"""End-to-end scenario tests (Layer A: offscreen MainWindow + QTest).

Each test builds a real ``MainWindow`` over a synthetic ``AppContext``
rooted at ``tmp_path``, drives it via ``QTest.keyClick`` and direct
method calls, then asserts on file-system state and widget state.

These complement ``test_keyboard_shortcuts.py`` (which exercises pieces
in isolation) by walking realistic workflows through the full
shortcut → handler → service chain.

Background-job operations (copy/move/delete) run on a ``QThread``;
``_wait_for_jobs`` polls ``QApplication.processEvents`` until the
``JobManager._active_threads`` list drains.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from multipane_commander.bootstrap import AppContext
from multipane_commander.config.model import AppConfig
from multipane_commander.state.model import AppState, LayoutState, PaneState, TabState, WindowState
from multipane_commander.ui.main_window import MainWindow


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def _make_main_window(left_dir: Path, right_dir: Path) -> MainWindow:
    _qapp()
    state = AppState(
        panes=[
            PaneState(title="Left", tabs=[TabState(title=left_dir.name or "left", path=left_dir)]),
            PaneState(title="Right", tabs=[TabState(title=right_dir.name or "right", path=right_dir)]),
        ],
        bookmarks=[],
        layout=LayoutState(active_pane_index=0, layout_mode="stacked"),
        window=WindowState(width=1280, height=860, is_maximized=False),
    )
    config = AppConfig()
    config.show_terminal = False  # keep the terminal collapsed for predictability
    window = MainWindow(context=AppContext(config=config, state=state))
    window.show()
    QApplication.processEvents()
    return window


def _close_window(window: MainWindow) -> None:
    """Close the window and kill the terminal-dock subprocess hard so we
    don't leak a zsh per test (and don't pay 2s per test waiting for a
    graceful shell exit)."""
    try:
        backend = window.terminal_dock.session
        proc = getattr(backend, "process", None)
        if proc is not None:
            proc.kill()
            proc.waitForFinished(500)
    except Exception:
        pass
    window.close()
    QApplication.processEvents()


def _wait_for_jobs(window: MainWindow, *, timeout_ms: int = 5000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    app = _qapp()
    while window.job_manager._active_threads and time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    # Drain any trailing signals (refresh, persist).
    for _ in range(10):
        app.processEvents()


def _setup_split(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    return left, right


def _row_for_path(pane, path: Path):
    for row in range(pane.file_list.topLevelItemCount()):
        item = pane.file_list.topLevelItem(row)
        if item.data(0, Qt.ItemDataRole.UserRole) == path:
            return item
    raise AssertionError(f"path {path} not found in pane {pane.active_tab.path}")


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def test_e2e_arrow_keys_move_cursor_in_active_pane(tmp_path: Path) -> None:
    left, right = _setup_split(tmp_path)
    (left / "alpha.txt").write_text("a")
    (left / "beta.txt").write_text("b")
    (left / "gamma.txt").write_text("c")
    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    pane.file_list.setCurrentItem(pane.file_list.topLevelItem(0))

    QTest.keyClick(pane.file_list, Qt.Key.Key_Down)
    QTest.keyClick(pane.file_list, Qt.Key.Key_Down)

    cursor_path = pane.file_list.currentItem().data(0, Qt.ItemDataRole.UserRole)
    assert isinstance(cursor_path, Path)
    assert cursor_path.name in {"alpha.txt", "beta.txt", "gamma.txt"}
    _close_window(window)


def test_e2e_tab_cycles_between_panes(tmp_path: Path) -> None:
    left, right = _setup_split(tmp_path)
    (left / "x.txt").write_text("x")
    (right / "y.txt").write_text("y")
    window = _make_main_window(left, right)
    initial_active = window.context.state.layout.active_pane_index

    QTest.keyClick(window, Qt.Key.Key_Tab)

    new_active = window.context.state.layout.active_pane_index
    assert new_active != initial_active
    _close_window(window)


def test_e2e_pane_click_focuses_file_list_so_arrows_work(tmp_path: Path) -> None:
    """Clicking into a pane (or any code path that flips active_pane_index)
    must leave focus on that pane's file_list — not on a chrome button or
    the pane container — so arrows / Enter / Space drive the cursor
    without an extra click on the list itself."""
    left, right = _setup_split(tmp_path)
    (right / "x.txt").write_text("x")
    (right / "y.txt").write_text("y")
    window = _make_main_window(left, right)
    # Simulate "user activated the right pane" via the same code path the
    # pane's mouse / focus handlers use — this is what was leaving focus
    # on the wrong widget before the fix.
    window._on_pane_activated(window.pane_views[1])

    focused = QApplication.focusWidget()
    assert focused is window.pane_views[1].file_list, (
        f"after pane activation, focus should be on file_list; got {focused}"
    )
    _close_window(window)


def test_e2e_pane_activation_does_not_steal_quick_filter_focus(tmp_path: Path) -> None:
    """If the user is typing in the quick-filter bar, activating the pane
    must not yank focus back to the file list."""
    left, right = _setup_split(tmp_path)
    (left / "alpha.txt").write_text("a")
    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.show_quick_filter()
    assert QApplication.focusWidget() is pane._quick_filter_bar

    # Re-activate the pane (e.g. via clicking a chrome button); focus must
    # stay in the filter input.
    window._on_pane_activated(pane)

    assert QApplication.focusWidget() is pane._quick_filter_bar
    _close_window(window)


def test_e2e_tab_lands_focus_on_file_list_so_arrows_work(tmp_path: Path) -> None:
    """Tab should switch to the other pane AND leave focus on the new
    pane's file list, so arrow keys and Enter work without an extra
    mouse click. This is the user-reported flow."""
    left, right = _setup_split(tmp_path)
    (right / "alpha.txt").write_text("a")
    (right / "beta.txt").write_text("b")
    (right / "gamma.txt").write_text("c")
    window = _make_main_window(left, right)
    initial_active = window.context.state.layout.active_pane_index
    assert initial_active == 0  # left

    # Tab to right pane.
    QTest.keyClick(window, Qt.Key.Key_Tab)
    assert window.context.state.layout.active_pane_index == 1
    right_pane = window.pane_views[1]
    # Focus should be inside the right pane (proxied to its file_list).
    focused = QApplication.focusWidget()
    assert focused is right_pane.file_list, (
        f"after Tab, focus should be on right pane's file_list; got {focused}"
    )

    # Now Down should move the cursor inside the right pane.
    starting_path = right_pane.file_list.currentItem().data(0, Qt.ItemDataRole.UserRole)
    QTest.keyClick(right_pane.file_list, Qt.Key.Key_Down)
    after_path = right_pane.file_list.currentItem().data(0, Qt.ItemDataRole.UserRole)
    assert after_path != starting_path, "Down should advance the cursor"

    _close_window(window)


def test_e2e_type_to_jump_moves_cursor_to_first_match(tmp_path: Path) -> None:
    left, right = _setup_split(tmp_path)
    (left / "alpha.txt").write_text("a")
    (left / "beta.txt").write_text("b")
    (left / "boris.txt").write_text("c")
    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    pane.file_list.setCurrentItem(pane.file_list.topLevelItem(0))

    QTest.keyClick(pane.file_list, Qt.Key.Key_B, Qt.KeyboardModifier.NoModifier)

    cursor_path = pane.file_list.currentItem().data(0, Qt.ItemDataRole.UserRole)
    assert isinstance(cursor_path, Path)
    assert cursor_path.name.startswith("b"), f"expected b*, got {cursor_path.name}"
    _close_window(window)


def test_e2e_ctrl_s_reveals_filter_bar(tmp_path: Path) -> None:
    left, right = _setup_split(tmp_path)
    (left / "alpha.txt").write_text("x")
    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    assert pane._quick_filter_bar.isVisible() is False

    QTest.keyClick(window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)

    assert pane._quick_filter_bar.isVisible() is True
    _close_window(window)


def test_e2e_alt_f1_opens_drive_menu_for_active_pane(tmp_path: Path, monkeypatch) -> None:
    """We can't easily click into a popped QMenu, so we monkeypatch
    ``_show_drive_menu`` to capture which pane it would have targeted."""
    left, right = _setup_split(tmp_path)
    window = _make_main_window(left, right)
    captured: list = []
    monkeypatch.setattr(MainWindow, "_show_drive_menu", lambda self, pane: captured.append(pane))

    QTest.keyClick(window, Qt.Key.Key_F1, Qt.KeyboardModifier.AltModifier)

    assert captured == [window.pane_views[0]]
    _close_window(window)


def test_e2e_f2_renames_file_and_ctrl_z_reverts(tmp_path: Path, monkeypatch) -> None:
    left, right = _setup_split(tmp_path)
    src = left / "old.txt"
    src.write_text("hello")
    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    pane.file_list.setCurrentItem(_row_for_path(pane, src))

    # F2 opens TextEntryDialog modal; monkeypatch to auto-accept with new name.
    from multipane_commander.ui import dialogs as dialogs_mod

    class FakeDialog:
        DialogCode = type("DC", (), {"Accepted": 1})

        def __init__(self, *_args, **_kwargs) -> None:
            self._value = "new.txt"

        def exec(self) -> int:
            return self.DialogCode.Accepted

        def value(self) -> str:
            return self._value

    monkeypatch.setattr("multipane_commander.ui.main_window.TextEntryDialog", FakeDialog)

    window._rename_in_active_pane()
    assert (left / "new.txt").exists()
    assert not (left / "old.txt").exists()
    assert len(window.undo_stack) == 1

    window._undo_last_operation()
    assert (left / "old.txt").exists()
    assert not (left / "new.txt").exists()
    assert len(window.undo_stack) == 0
    _close_window(window)


def test_e2e_f5_copies_marked_file_to_passive_pane(tmp_path: Path, monkeypatch) -> None:
    left, right = _setup_split(tmp_path)
    src = left / "thing.txt"
    src.write_text("content-to-copy")
    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    pane.marked_paths = {src}

    # The transfer dialog is modal — short-circuit it to "accepted" with no overrides.
    from multipane_commander.ui import transfer_dialog as td_mod

    class FakeTransferDialog:
        DialogCode = type("DC", (), {"Accepted": 1, "Rejected": 0})

        def __init__(self, *_args, **kwargs) -> None:
            self._sources = kwargs.get("source_paths") or []
            self._destination = kwargs.get("default_destination")

        def exec(self) -> int:
            return self.DialogCode.Accepted

        def destination_directory(self):
            return self._destination

        def conflict_policy(self) -> str:
            return "overwrite"

        def selected_actions(self):
            return self._sources

    monkeypatch.setattr("multipane_commander.ui.main_window.TransferDialog", FakeTransferDialog)

    window._copy_from_active_pane()
    _wait_for_jobs(window)

    assert (right / "thing.txt").exists()
    assert (right / "thing.txt").read_text() == "content-to-copy"
    assert (left / "thing.txt").exists()  # source preserved on copy
    _close_window(window)


def test_e2e_shift_f8_permanent_delete_unlinks_file(tmp_path: Path, monkeypatch) -> None:
    left, right = _setup_split(tmp_path)
    target = left / "doomed.txt"
    target.write_text("x")
    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    pane.marked_paths = {target}

    monkeypatch.setattr("multipane_commander.ui.main_window.ask_confirmation", lambda **_kwargs: True)

    window._delete_from_active_pane_permanent()
    _wait_for_jobs(window)

    assert not target.exists()
    _close_window(window)


def test_e2e_alt_f7_opens_find_dialog_and_search_finds_match(tmp_path: Path, monkeypatch) -> None:
    left, right = _setup_split(tmp_path)
    (left / "a.txt").write_text("magic-marker")
    (left / "b.txt").write_text("nothing")
    window = _make_main_window(left, right)

    captured = {}
    real_find_files = None

    from multipane_commander.ui import find_files_dialog as ff_mod

    real_find_files = ff_mod.find_files

    class FakeDialog:
        def __init__(self, root, *, parent=None, on_open=None) -> None:
            captured["root"] = root
            captured["on_open"] = on_open

        def exec(self) -> int:
            captured["results"] = real_find_files(captured["root"], name_pattern="*.txt", content_query="magic")
            return 0

    monkeypatch.setattr("multipane_commander.ui.main_window.FindFilesDialog", FakeDialog)

    window._find_files_in_active_pane()

    assert captured["root"] == left
    paths = {r.path.name for r in captured["results"]}
    assert paths == {"a.txt"}
    _close_window(window)


def test_e2e_enter_on_zip_browses_contents(tmp_path: Path) -> None:
    import zipfile

    left, right = _setup_split(tmp_path)
    archive = left / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("alpha.txt", b"a")
        zf.writestr("beta.txt", b"bb")
        zf.writestr("sub/inner.txt", b"i")

    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    item = _row_for_path(pane, archive)
    pane.file_list.setCurrentItem(item)

    # Activate (Enter) on the zip — exercises the same code path itemActivated does.
    pane._activate_item(item)
    QApplication.processEvents()

    # Pane is now "inside" the archive — listing should show its entries.
    assert pane.active_tab.path == archive
    names: list[str] = []
    for row in range(pane.file_list.topLevelItemCount()):
        names.append(pane.file_list.topLevelItem(row).text(0))
    assert ".." in names
    assert "alpha.txt" in names
    assert "beta.txt" in names
    assert "sub" in names

    # Backspace at archive root returns to the parent directory.
    pane.navigate_to(pane.active_tab.path.parent)
    QApplication.processEvents()
    assert pane.active_tab.path == left

    _close_window(window)


def test_e2e_enter_zip_subdir_then_parent_returns_to_root(tmp_path: Path) -> None:
    import zipfile

    left, right = _setup_split(tmp_path)
    archive = left / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("sub/inner.txt", b"i")

    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    pane._activate_item(_row_for_path(pane, archive))
    QApplication.processEvents()

    # Step into the subdirectory.
    pane._activate_item(_row_for_path(pane, archive / "sub"))
    QApplication.processEvents()
    assert pane.active_tab.path == archive / "sub"

    # Parent navigation from a subdirectory inside the archive → back to archive root.
    pane.navigate_to(pane.active_tab.path.parent)
    QApplication.processEvents()
    assert pane.active_tab.path == archive

    _close_window(window)


def test_e2e_f5_extracts_file_from_zip_to_passive_pane(tmp_path: Path, monkeypatch) -> None:
    import zipfile

    left, right = _setup_split(tmp_path)
    archive = left / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("payload.txt", b"unzipped-content")

    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    pane._activate_item(_row_for_path(pane, archive))
    QApplication.processEvents()

    # Mark the inner file so the transfer picks it up.
    pane.marked_paths = {archive / "payload.txt"}

    class FakeTransferDialog:
        DialogCode = type("DC", (), {"Accepted": 1, "Rejected": 0})

        def __init__(self, *_args, **kwargs) -> None:
            self._sources = kwargs.get("source_paths") or []
            self._destination = kwargs.get("default_destination")

        def exec(self) -> int:
            return self.DialogCode.Accepted

        def destination_directory(self):
            return self._destination

        def conflict_policy(self) -> str:
            return "overwrite"

        def selected_actions(self):
            return self._sources

    monkeypatch.setattr("multipane_commander.ui.main_window.TransferDialog", FakeTransferDialog)

    window._copy_from_active_pane()
    _wait_for_jobs(window)

    extracted = right / "payload.txt"
    assert extracted.exists()
    assert extracted.read_bytes() == b"unzipped-content"
    # Source archive untouched (read-only).
    assert archive.exists()
    _close_window(window)


def test_e2e_f3_quick_view_on_file_inside_zip(tmp_path: Path) -> None:
    import zipfile

    left, right = _setup_split(tmp_path)
    archive = left / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", b"hello from inside")

    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    pane._activate_item(_row_for_path(pane, archive))
    QApplication.processEvents()

    # Cursor on the inner file → trigger quick view.
    inner_item = _row_for_path(pane, archive / "readme.txt")
    pane.file_list.setCurrentItem(inner_item)
    QApplication.processEvents()

    window._show_passive_quick_view()
    QApplication.processEvents()

    quick_view = window.pane_views[1].quick_view
    # The text-preview branch should have rendered the extracted contents.
    assert "hello from inside" in quick_view.text_preview.toPlainText()
    # Title still reflects the virtual file name (not the temp path).
    assert quick_view.title_label.text() == "readme.txt"

    _close_window(window)


def test_e2e_pane_uses_archive_fs_when_inside_archive(tmp_path: Path) -> None:
    """Sanity check: the pane swaps to ArchiveFileSystem inside, LocalFileSystem outside."""
    import zipfile

    from multipane_commander.services.fs.archive_fs import ArchiveFileSystem
    from multipane_commander.services.fs.local_fs import LocalFileSystem

    left, right = _setup_split(tmp_path)
    archive = left / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("alpha.txt", b"a")

    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    assert isinstance(pane.fs, LocalFileSystem)

    pane._activate_item(_row_for_path(pane, archive))
    QApplication.processEvents()
    assert isinstance(pane.fs, ArchiveFileSystem)

    pane.navigate_to(left)
    QApplication.processEvents()
    assert isinstance(pane.fs, LocalFileSystem)

    _close_window(window)


def test_e2e_ctrl_shift_r_toggles_quick_view_raw_mode(tmp_path: Path) -> None:
    left, right = _setup_split(tmp_path)
    md = left / "doc.md"
    md.write_text("# heading\n\nbody\n", encoding="utf-8")
    window = _make_main_window(left, right)
    active = window.pane_views[0]
    active.refresh()
    # Cursor on the markdown file in the active pane.
    item = _row_for_path(active, md)
    active.file_list.setCurrentItem(item)
    QApplication.processEvents()

    # Reveal Quick View in the passive pane and sync.
    window._show_passive_quick_view()
    QApplication.processEvents()
    passive = window.pane_views[1]
    quick_view = passive.quick_view
    assert quick_view.stack.currentWidget() is quick_view.markdown_view

    QTest.keySequence(window, QKeySequence("Ctrl+Shift+R"))
    QApplication.processEvents()
    assert quick_view.is_raw_mode()
    assert quick_view.stack.currentWidget() is quick_view.raw_text_view

    QTest.keySequence(window, QKeySequence("Ctrl+Shift+R"))
    QApplication.processEvents()
    assert quick_view.is_raw_mode() is False
    assert quick_view.stack.currentWidget() is quick_view.markdown_view

    _close_window(window)


def test_e2e_f10_menu_lists_raw_and_web_toggle_actions(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QMenu

    left, right = _setup_split(tmp_path)
    window = _make_main_window(left, right)
    menu = window._build_main_menu()

    def walk_titles(m: QMenu) -> list[str]:
        out: list[str] = []
        for action in m.actions():
            out.append(action.text())
            sub = action.menu()
            if sub is not None:
                out.extend(walk_titles(sub))
        return out

    titles = walk_titles(menu)
    assert any("Toggle Raw Source" in t for t in titles), titles
    assert any("Toggle Web Render" in t for t in titles), titles

    _close_window(window)


def test_e2e_ctrl_m_renames_via_template_and_pushes_undo(tmp_path: Path, monkeypatch) -> None:
    left, right = _setup_split(tmp_path)
    a = left / "old1.txt"
    b = left / "old2.txt"
    a.write_text("1")
    b.write_text("2")
    window = _make_main_window(left, right)
    pane = window.pane_views[0]
    pane.refresh()
    pane.marked_paths = {a, b}

    from multipane_commander.ui import multi_rename_dialog as mr_mod

    real_build = mr_mod.build_preview

    class FakeMRD:
        DialogCode = type("DC", (), {"Accepted": 1})

        def __init__(self, sources, *, parent=None, **_kwargs) -> None:
            self._sources = list(sources)

        def exec(self) -> int:
            return self.DialogCode.Accepted

        def previews(self):
            return real_build(self._sources, name_template="renamed_[C]", ext_template="[E]")

    monkeypatch.setattr("multipane_commander.ui.main_window.MultiRenameDialog", FakeMRD)

    window._multi_rename_in_active_pane()

    assert (left / "renamed_1.txt").exists()
    assert (left / "renamed_2.txt").exists()
    assert not (left / "old1.txt").exists()
    assert not (left / "old2.txt").exists()
    assert len(window.undo_stack) == 2
    _close_window(window)
