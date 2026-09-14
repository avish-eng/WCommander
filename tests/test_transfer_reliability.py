from pathlib import Path
from threading import Event
import zipfile

import pytest

from multipane_commander.services.fs.archive_fs import ArchiveFileSystem, ArchiveReadError
from multipane_commander.services.fs.local_fs import LocalFileSystem, OperationCancelled
from multipane_commander.services.jobs.manager import _FileJobWorker
from multipane_commander.services.jobs.model import FileJobAction
from multipane_commander.services.jobs.transfer import TransferExecutor
from multipane_commander.services.undo import UndoRecord, UndoStack


@pytest.mark.parametrize("failure_call", [2, 3])
def test_failed_move_restores_both_files(tmp_path, monkeypatch, failure_call):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    fs = LocalFileSystem()
    original = fs.move_entry
    calls = 0

    def move(src, dst):
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise OSError("locked destination")
        original(src, dst)

    monkeypatch.setattr(fs, "move_entry", move)
    with pytest.raises(OSError, match="locked"):
        fs.replace_entry(source, target, operation="move")
    assert source.read_bytes() == b"new"
    assert target.read_bytes() == b"old"
    assert set(tmp_path.iterdir()) == {source, target}


@pytest.mark.parametrize("existing", [False, True])
def test_cancel_mid_file_preserves_source_and_destination(tmp_path, existing):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"x" * (3 * 1024 * 1024))
    if existing:
        target.write_bytes(b"old")
    cancelled = Event()
    executor = TransferExecutor(cancelled, lambda progress: None)
    executor.fs.on_bytes = lambda count: cancelled.set()
    with pytest.raises(OperationCancelled):
        executor.execute(FileJobAction("copy", source, target, replace_existing=existing))
    assert source.stat().st_size == 3 * 1024 * 1024
    assert target.read_bytes() == b"old" if existing else not target.exists()
    assert not list(tmp_path.glob(".*mpc*"))


def test_cancel_during_directory_copy_leaves_no_partial_destination(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    for i in range(5):
        (source / str(i)).write_bytes(b"x" * 100)
    token = Event()
    executor = TransferExecutor(token, lambda progress: None)
    executor.fs.on_bytes = lambda count: token.set()
    with pytest.raises(OperationCancelled):
        executor.execute(FileJobAction("copy", source, target))
    assert len(list(source.iterdir())) == 5
    assert not target.exists()
    assert not list(tmp_path.glob(".*mpc*"))


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_archive_file_transfers_as_regular_file(tmp_path, operation):
    source, target = tmp_path / "source.zip", tmp_path / "target.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("a.txt", "hello")
    expected = source.read_bytes()
    worker = _FileJobWorker([FileJobAction(operation, source, target)])
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert not results[0].errors
    assert target.read_bytes() == expected
    assert source.exists() == (operation == "copy")


@pytest.mark.parametrize("explicit", [False, True])
def test_extract_nested_archive_folder(tmp_path, explicit):
    source, target = tmp_path / "source.zip", tmp_path / "target"
    with zipfile.ZipFile(source, "w") as archive:
        if explicit:
            archive.writestr("folder/", "")
        archive.writestr("folder/sub/a.txt", "hello")
        archive.writestr("folder/empty/", "")
        archive.writestr("outside.txt", "outside")
    ArchiveFileSystem().extract_entry_to(source / "folder", target)
    assert (target / "sub/a.txt").read_text() == "hello"
    assert (target / "empty").is_dir()
    assert not (target / "outside.txt").exists()


@pytest.mark.parametrize("unsafe", ["folder/../../escape", "folder/..\\escape", "C:/escape"])
def test_unsafe_archive_does_not_modify_existing_destination(tmp_path, unsafe):
    source, target = tmp_path / "source.zip", tmp_path / "target"
    target.mkdir()
    (target / "old").write_text("old")
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("folder/good", "good")
        archive.writestr(unsafe, "bad")
    with pytest.raises(ArchiveReadError):
        ArchiveFileSystem().extract_entry_to(source / "folder", target)
    assert [p.name for p in target.iterdir()] == ["old"]
    assert not list(tmp_path.glob(".*mpc*"))


def test_undo_failure_can_be_retried(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    target.write_text("renamed")
    source.write_text("conflict")
    stack = UndoStack()
    stack.push(UndoRecord("rename", source, target))
    with pytest.raises(FileExistsError):
        stack.undo(LocalFileSystem())
    assert len(stack) == 1
    source.unlink()
    assert stack.undo(LocalFileSystem())
    assert source.read_text() == "renamed"
    assert len(stack) == 0


def test_grouped_undo_retries_only_remaining_records(tmp_path):
    stack = UndoStack()
    a, b, x, y = [tmp_path / name for name in ("a", "b", "x", "y")]
    x.write_text("a")
    y.write_text("b")
    a.write_text("conflict")
    with stack.group():
        stack.push(UndoRecord("rename", a, x))
        stack.push(UndoRecord("rename", b, y))
    assert len(stack) == 1
    with pytest.raises(FileExistsError):
        stack.undo(LocalFileSystem())
    assert b.read_text() == "b"
    assert not y.exists()
    a.unlink()
    assert stack.undo(LocalFileSystem())
    assert a.read_text() == "a"
    assert len(stack) == 0


def test_move_overwrite_undo_restores_both_originals(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_text("new")
    target.write_text("old")
    action = FileJobAction("move", source, target, replace_existing=True)
    progress = []
    TransferExecutor(Event(), progress.append).execute(action)
    stack = UndoStack()
    stack.push(UndoRecord("move", source, target, action.undo_backup))
    stack.undo(LocalFileSystem())
    assert source.read_text() == "new"
    assert target.read_text() == "old"
    assert progress[-1].bytes_done == progress[-1].bytes_total == 3
    assert not list(tmp_path.glob(".*mpc*"))


def test_folder_cannot_be_copied_into_itself(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="into itself"):
        TransferExecutor(Event(), lambda progress: None).execute(
            FileJobAction("copy", source, source / "child")
        )
    assert not list(source.iterdir())


def test_archive_root_directory_marker_is_not_a_child(tmp_path):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("./", "")
        writer.writestr("./a.txt", "content")
    assert [entry.name for entry in ArchiveFileSystem().list_dir(archive)] == ["a.txt"]


def test_copy_failure_keeps_original_target(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_text("new")
    target.write_text("old")
    executor = TransferExecutor(Event(), lambda progress: None)

    def fail(src, dst):
        Path(dst).write_text("partial")
        raise OSError("disk full")

    monkeypatch.setattr(executor.fs, "_copy_file", fail)
    with pytest.raises(OSError, match="disk full"):
        executor.execute(FileJobAction("copy", source, target, replace_existing=True))
    assert target.read_text() == "old"
    assert source.read_text() == "new"
    assert not list(tmp_path.glob(".*mpc*"))


@pytest.mark.parametrize("cancel", [False, True])
def test_cross_volume_move_copies_before_removing_source(tmp_path, monkeypatch, cancel):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    target.write_text("old")
    token = Event()
    executor = TransferExecutor(token, lambda progress: None)
    monkeypatch.setattr(executor.fs, "_cross_device", lambda src, dst: True)

    def advance(count):
        assert source.exists()
        if cancel:
            token.set()

    executor.fs.on_bytes = advance
    action = FileJobAction("move", source, target, replace_existing=True)
    if cancel:
        with pytest.raises(OperationCancelled):
            executor.execute(action)
        assert source.stat().st_size == 2 * 1024 * 1024
        assert target.read_text() == "old"
    else:
        executor.execute(action)
        assert not source.exists()
        assert target.stat().st_size == 2 * 1024 * 1024
        assert action.undo_backup.read_text() == "old"


@pytest.mark.parametrize("cancel_after", [1, 2])
def test_cancel_after_move_staging_restores_both_originals(tmp_path, monkeypatch, cancel_after):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_text("new")
    target.write_text("old")
    token = Event()
    executor = TransferExecutor(token, lambda progress: None)
    original = executor.fs.move_entry
    calls = 0

    def move(src, dst):
        nonlocal calls
        original(src, dst)
        calls += 1
        if calls == cancel_after:
            token.set()

    monkeypatch.setattr(executor.fs, "move_entry", move)
    with pytest.raises(OperationCancelled):
        executor.execute(FileJobAction("move", source, target, replace_existing=True))
    assert source.read_text() == "new"
    assert target.read_text() == "old"
    assert set(tmp_path.iterdir()) == {source, target}
