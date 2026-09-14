import os
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
import pytest

from multipane_commander.services.bookmarks import BookmarkStore
from multipane_commander.services.fs.local_fs import LocalFileSystem
from multipane_commander.services.search import find_files
from multipane_commander.state.model import PaneState, TabState
from multipane_commander.ui.find_files_dialog import FindFilesDialog
from multipane_commander.ui.pane_view import PaneView
from ui_wait import wait_for_pane, wait_until


@pytest.fixture
def panes():
    app = QApplication.instance() or QApplication([])
    created = []

    def create(path):
        pane = PaneView(
            PaneState(title="Test", tabs=[TabState(title="Test", path=path)]),
            bookmark_store=BookmarkStore(),
            active=True,
        )
        pane.resize(600, 500)
        pane.show()
        created.append(pane)
        return pane

    yield create
    for pane in created:
        pane.close()
    app.processEvents()


def test_slow_listing_does_not_block_ui(panes, tmp_path, monkeypatch):
    started, release = Event(), Event()
    original = LocalFileSystem.list_dir

    def slow(fs, path):
        started.set()
        assert release.wait(5)
        return original(fs, path)

    monkeypatch.setattr(LocalFileSystem, "list_dir", slow)
    pane = panes(tmp_path)
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    try:
        wait_until(lambda: started.is_set() and bool(heartbeat))
        assert pane._tasks.is_running("directory")
    finally:
        release.set()
    wait_for_pane(pane)


def test_stale_listing_cannot_replace_new_directory(panes, tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "stale").touch()
    (new / "fresh").touch()
    started, release = Event(), Event()
    original = LocalFileSystem.list_dir

    def slow(fs, path):
        if path == old:
            started.set()
            assert release.wait(5)
        return original(fs, path)

    monkeypatch.setattr(LocalFileSystem, "list_dir", slow)
    pane = panes(old)
    try:
        wait_until(started.is_set)
        pane.navigate_to(new)
        wait_for_pane(pane)
        assert pane.current_directory() == new
        assert [entry.name for entry in pane._current_entries] == ["fresh"]
    finally:
        release.set()
    wait_until(lambda: pane.current_path() == new / "fresh")
    assert pane._displayed_path == new


def test_external_change_preserves_cursor_marks_filter_and_scroll(panes, tmp_path):
    for index in range(250):
        (tmp_path / f"item{index:03}.txt").touch()
    pane = panes(tmp_path)
    wait_for_pane(pane)
    selected = tmp_path / "item120.txt"
    pane._set_current_path(selected)
    pane.marked_paths.add(selected)
    pane._quick_filter_bar.setText("item")
    pane.file_list.verticalScrollBar().setValue(75)
    scroll = pane.file_list.verticalScrollBar().value()
    external = tmp_path / "item999.txt"
    external.write_text("from terminal")
    wait_until(lambda: any(e.path == external for e in pane._current_entries))
    wait_for_pane(pane)
    assert pane.current_path() == selected
    assert pane.marked_paths == {selected}
    assert pane._quick_filter_text == "item"
    assert pane.file_list.verticalScrollBar().value() == scroll


def test_thumbnail_decoding_is_lazy(panes, tmp_path, monkeypatch):
    image = QImage(40, 40, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    for index in range(35):
        image.save(str(tmp_path / f"image{index:02}.png"))
    from multipane_commander.ui import pane_view

    original = pane_view.QImageReader
    decoded = []

    def reader(path):
        decoded.append(path)
        return original(path)

    monkeypatch.setattr(pane_view, "QImageReader", reader)
    pane = panes(tmp_path)
    wait_for_pane(pane)
    assert not decoded
    assert pane.thumbnail_list.count() == 0
    pane.set_thumbnail_mode_enabled(True)
    wait_until(lambda: bool(decoded) and not pane._thumbnail_pending)
    assert len(decoded) < 35


def test_search_streams_batches_and_stops(panes, tmp_path):
    for index in range(125):
        (tmp_path / f"{index}.txt").write_text("needle")
    token = Event()
    batches = []

    def receive(batch):
        batches.append(batch)
        token.set()

    results = find_files(tmp_path, content_query="needle", cancelled=token, on_batch=receive)
    assert len(results) == len(batches[0]) == 50


def test_search_cancel_keeps_dialog_responsive(panes, tmp_path, monkeypatch):
    panes(tmp_path)
    started, release = Event(), Event()

    def slow(root, **options):
        started.set()
        assert release.wait(5)
        assert options["cancelled"].is_set()
        return []

    monkeypatch.setattr("multipane_commander.ui.find_files_dialog.find_files", slow)
    dialog = FindFilesDialog(tmp_path)
    dialog.show()
    try:
        dialog._run_search()
        wait_until(started.is_set)
        dialog._run_search()
        assert "Cancelled" in dialog._summary.text()
        assert not dialog._tasks.is_running("search")
    finally:
        release.set()
        dialog.close()


def test_directory_size_completes_in_background(panes, tmp_path):
    directory = tmp_path / "folder"
    directory.mkdir()
    (directory / "a").write_bytes(b"12345")
    pane = panes(tmp_path)
    wait_for_pane(pane)
    pane._set_current_path(directory)
    item = pane.file_list.currentItem()
    pane._compute_and_apply_dir_size(item, directory)
    wait_until(lambda: not pane._tasks.is_running("size:" + str(directory)))
    assert item.data(0, Qt.ItemDataRole.UserRole + 2) == 5


@pytest.mark.parametrize("pattern", ["*.txt", "**/*.txt", "sub/**/*.txt", "sub/*.txt"])
def test_background_search_preserves_recursive_glob_semantics(tmp_path, pattern):
    (tmp_path / "sub/deep").mkdir(parents=True)
    for name in ("root.txt", "sub/child.txt", "sub/deep/nested.txt", "sub/deep/other.py"):
        (tmp_path / name).touch()
    assert {r.path for r in find_files(tmp_path, name_pattern=pattern)} == {
        p for p in tmp_path.rglob(pattern) if p.is_file()
    }


def test_transfer_cancel_button_interrupts_running_worker(panes, tmp_path, monkeypatch):
    import time
    from threading import get_ident
    from multipane_commander.services.jobs.manager import JobManager
    from multipane_commander.services.jobs.model import FileJobAction

    pane = panes(tmp_path)
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_text("new")
    destination.write_text("old")
    started = Event()

    def slow_copy(fs, src, dst):
        with open(dst, "wb") as output:
            output.write(b"partial")
        started.set()
        for _ in range(1000):
            fs.check_cancel()
            time.sleep(0.005)
        raise AssertionError("Cancellation did not reach the worker")

    monkeypatch.setattr(LocalFileSystem, "_copy_file", slow_copy)
    manager = JobManager(pane)
    results, callback_threads = [], []

    def finished(result):
        results.append(result)
        callback_threads.append(get_ident())

    manager.start_file_job(
        parent=pane,
        title="Copy",
        actions=[FileJobAction("copy", source, destination, replace_existing=True)],
        on_finished=finished,
    )
    wait_until(started.is_set)
    dialog = next(iter(manager._progress_dialogs.values()))
    dialog.cancel_button.click()
    wait_until(lambda: bool(results) and not manager.has_active_jobs())
    assert results[0].cancelled
    assert callback_threads == [get_ident()]
    assert source.read_text() == "new"
    assert destination.read_text() == "old"
    dialog.cancel_button.click()  # Now labelled Close; dismiss the completed job.
    assert not dialog.isVisible()


def test_back_restores_cached_rows_while_revalidation_is_blocked(panes, tmp_path, monkeypatch):
    child = tmp_path / "child"
    child.mkdir()
    for index in range(60):
        (tmp_path / f"item{index:03}.txt").touch()
    pane = panes(tmp_path)
    wait_for_pane(pane)
    selected = tmp_path / "item040.txt"
    pane._set_current_path(selected)
    pane.file_list.verticalScrollBar().setValue(20)
    scroll = pane.file_list.verticalScrollBar().value()
    pane.navigate_to(child)
    wait_for_pane(pane)
    started, release = Event(), Event()
    original = LocalFileSystem.list_dir

    def slow(fs, path):
        if path == tmp_path:
            started.set()
            assert release.wait(5)
        return original(fs, path)

    monkeypatch.setattr(LocalFileSystem, "list_dir", slow)
    try:
        pane._navigate_back()
        # No event pumping or disk-read completion is needed to restore Back.
        assert pane.current_path() == selected
        assert pane.file_list.verticalScrollBar().value() == scroll
        assert len(pane._current_entries) == 61
        wait_until(started.is_set)
        (tmp_path / "new-external-file.txt").touch()
    finally:
        release.set()
    wait_for_pane(pane)
    assert any(e.name == "new-external-file.txt" for e in pane._current_entries)
    assert pane.current_path() == selected


def test_row_styles_invalidate_layout_once_without_recursive_status_updates(panes, tmp_path):
    for index in range(250):
        (tmp_path / f"item{index:03}.txt").touch()
    pane = panes(tmp_path)
    wait_for_pane(pane)
    changes, previews = [], []
    pane.file_list.model().dataChanged.connect(lambda *args: changes.append(args))
    pane.current_path_changed.connect(previews.append)
    pane.marked_paths.add(pane.current_path())
    pane._update_status()
    assert len(changes) == 1
    assert len(previews) == 1
    assert pane.file_list.currentItem().font(0).bold()
    changes.clear()
    pane._refresh_row_styles()
    assert not changes  # Unchanged rows must not force another layout pass.


def test_cached_folder_is_discarded_when_revalidation_fails(panes, tmp_path, monkeypatch):
    child = tmp_path / "child"
    child.mkdir()
    pane = panes(tmp_path)
    wait_for_pane(pane)
    pane.navigate_to(child)
    wait_for_pane(pane)

    def inaccessible(fs, path):
        raise PermissionError("Access denied")

    monkeypatch.setattr(LocalFileSystem, "list_dir", inaccessible)
    pane._navigate_back()
    assert pane._current_entries
    wait_for_pane(pane)
    assert not pane._current_entries
    assert tmp_path not in pane._directory_cache
    assert "Access denied" in pane.status.text()


def test_recent_directory_cache_is_bounded(panes, tmp_path):
    folders = [tmp_path / str(index) for index in range(12)]
    for folder in folders:
        folder.mkdir()
    pane = panes(folders[0])
    wait_for_pane(pane)
    for folder in folders[1:]:
        pane.navigate_to(folder)
        wait_for_pane(pane)
    assert len(pane._directory_cache) == 8
    assert folders[0] not in pane._directory_cache
    assert folders[-1] in pane._directory_cache


def test_mouse_back_does_not_repeat_native_icon_lookup_for_every_row(
    panes, tmp_path, monkeypatch
):
    from PySide6.QtCore import QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle

    child = tmp_path / "child"
    child.mkdir()
    (child / "nested.txt").touch()
    for index in range(200):
        (tmp_path / f"item{index:03}.txt").touch()
    pane = panes(tmp_path)
    wait_for_pane(pane)
    style_type = type(pane.style())
    original = style_type.standardIcon
    lookups = []

    def counted(style, icon, *args, **kwargs):
        if icon in (QStyle.StandardPixmap.SP_DirIcon, QStyle.StandardPixmap.SP_FileIcon):
            lookups.append(icon)
        return original(style, icon, *args, **kwargs)

    monkeypatch.setattr(style_type, "standardIcon", counted)
    # A style change should reload the two icons, but subsequent navigation
    # must not pay the native Windows lookup cost for every displayed entry.
    for expected_lookups in (2, 4):
        QApplication.sendEvent(pane, QEvent(QEvent.Type.StyleChange))
        pane.navigate_to(child)
        wait_for_pane(pane)
        QTest.mouseClick(pane.back_button, Qt.MouseButton.LeftButton)
        wait_for_pane(pane)
        assert pane.current_directory() == tmp_path
        assert len(pane._current_entries) == 201
        assert len(lookups) == expected_lookups
