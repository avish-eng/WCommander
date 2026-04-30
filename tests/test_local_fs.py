from pathlib import Path

from multipane_commander.services.fs.local_fs import LocalFileSystem


def test_list_dir_sorts_directories_before_files(tmp_path: Path) -> None:
    (tmp_path / "z-dir").mkdir()
    (tmp_path / "a-dir").mkdir()
    (tmp_path / "c-file.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "b-file.txt").write_text("world", encoding="utf-8")

    entries = LocalFileSystem().list_dir(tmp_path)

    assert [entry.name for entry in entries] == [
        "a-dir",
        "z-dir",
        "b-file.txt",
        "c-file.txt",
    ]


def test_copy_move_and_mkdir_work(tmp_path: Path) -> None:
    fs = LocalFileSystem()
    source_file = tmp_path / "source.txt"
    source_file.write_text("hello", encoding="utf-8")

    copied_file = tmp_path / "copied.txt"
    moved_file = tmp_path / "moved.txt"
    created_dir = tmp_path / "new-dir"

    fs.copy_entry(source_file, copied_file)
    fs.move_entry(copied_file, moved_file)
    fs.mkdir(created_dir)

    assert source_file.read_text(encoding="utf-8") == "hello"
    assert moved_file.read_text(encoding="utf-8") == "hello"
    assert not copied_file.exists()
    assert created_dir.is_dir()


def test_remove_existing_handles_files_and_directories(tmp_path: Path) -> None:
    fs = LocalFileSystem()
    file_path = tmp_path / "file.txt"
    dir_path = tmp_path / "dir"

    file_path.write_text("hello", encoding="utf-8")
    dir_path.mkdir()
    (dir_path / "child.txt").write_text("child", encoding="utf-8")

    fs.remove_existing(file_path)
    fs.remove_existing(dir_path)

    assert not file_path.exists()
    assert not dir_path.exists()


def test_rename_entry_renames_file(tmp_path: Path) -> None:
    fs = LocalFileSystem()
    source = tmp_path / "old.txt"
    destination = tmp_path / "new.txt"
    source.write_text("hello", encoding="utf-8")

    fs.rename_entry(source, destination)

    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "hello"


def test_replace_entry_stages_copy_before_replacing_destination(tmp_path: Path) -> None:
    fs = LocalFileSystem()
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")

    fs.replace_entry(source, destination, operation="copy")

    assert source.read_text(encoding="utf-8") == "new"
    assert destination.read_text(encoding="utf-8") == "new"
    assert not [path for path in tmp_path.iterdir() if "mpc-tmp" in path.name]


def test_replace_entry_moves_source_after_staging(tmp_path: Path) -> None:
    fs = LocalFileSystem()
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")

    fs.replace_entry(source, destination, operation="move")

    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "new"
    assert not [path for path in tmp_path.iterdir() if "mpc-tmp" in path.name]


def test_replace_entry_restores_destination_when_final_swap_fails(tmp_path: Path) -> None:
    fs = LocalFileSystem()
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")

    original_move_entry = fs.move_entry
    call_count = 0

    def patched_move_entry(src: Path, dst: Path) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            original_move_entry(src, dst)
            return
        raise OSError("swap failed")

    fs.move_entry = patched_move_entry  # type: ignore[method-assign]

    try:
        fs.replace_entry(source, destination, operation="move")
    except OSError as exc:
        assert str(exc) == "swap failed"
    else:
        raise AssertionError("Expected replace_entry to propagate the swap failure")

    assert destination.read_text(encoding="utf-8") == "old"
    temp_paths = [path for path in tmp_path.iterdir() if "mpc-tmp" in path.name or "mpc-bak" in path.name]
    assert not temp_paths
