"""Tests for the read-only ArchiveFileSystem (zip / tar / 7z, …)."""

from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from multipane_commander.services.fs.archive_fs import (
    ArchiveEntryNotFound,
    ArchiveFileSystem,
    ArchiveReadError,
    find_archive_root,
    inside_archive,
    is_archive_file,
    virtual_path,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def _make_tar(path: Path, entries: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            import io

            tf.addfile(info, io.BytesIO(data))
    return path


# --- Pure helpers -------------------------------------------------------------


def test_is_archive_file_recognises_zip(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"a.txt": b"a"})
    assert is_archive_file(zp) is True


def test_is_archive_file_rejects_directory(tmp_path: Path) -> None:
    assert is_archive_file(tmp_path) is False


def test_is_archive_file_rejects_plain_text(tmp_path: Path) -> None:
    plain = tmp_path / "notes.txt"
    plain.write_text("hi")
    assert is_archive_file(plain) is False


def test_is_archive_file_recognises_tar_gz(tmp_path: Path) -> None:
    tar_gz = tmp_path / "x.tar.gz"
    with tarfile.open(tar_gz, "w:gz") as tf:
        info = tarfile.TarInfo("a.txt")
        info.size = 1
        import io

        tf.addfile(info, io.BytesIO(b"a"))
    assert is_archive_file(tar_gz) is True


def test_find_archive_root_returns_self_for_archive(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"a.txt": b"a"})
    assert find_archive_root(zp) == zp


def test_find_archive_root_returns_root_for_inner(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"a.txt": b"a"})
    assert find_archive_root(zp / "a.txt") == zp


def test_find_archive_root_returns_root_for_deep_inner(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"sub/deep/file.txt": b"x"})
    assert find_archive_root(zp / "sub" / "deep" / "file.txt") == zp


def test_find_archive_root_returns_none_for_real_path(tmp_path: Path) -> None:
    plain = tmp_path / "notes.txt"
    plain.write_text("hi")
    assert find_archive_root(plain) is None
    assert find_archive_root(tmp_path) is None


def test_inside_archive_returns_root_and_inner(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"sub/file.txt": b"x"})
    ctx = inside_archive(zp / "sub" / "file.txt")
    assert ctx is not None
    root, inner = ctx
    assert root == zp
    assert str(inner) == "sub/file.txt"


def test_inside_archive_returns_empty_inner_for_root(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"a.txt": b"a"})
    ctx = inside_archive(zp)
    assert ctx is not None
    root, inner = ctx
    assert root == zp
    assert str(inner) == "."  # PurePosixPath("") stringifies as "."


def test_virtual_path_round_trips(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"a.txt": b"a"})
    p = virtual_path(zp, "sub/file.txt")
    assert p == zp / "sub" / "file.txt"
    ctx = inside_archive(p)
    assert ctx is not None
    assert ctx[0] == zp
    assert str(ctx[1]) == "sub/file.txt"


# --- ArchiveFileSystem.list_dir ------------------------------------------------


def test_list_dir_zip_root(tmp_path: Path) -> None:
    zp = _make_zip(
        tmp_path / "x.zip",
        {"a.txt": b"a", "b.txt": b"bb", "sub/inner.txt": b"i"},
    )
    fs = ArchiveFileSystem()
    entries = fs.list_dir(zp)
    names = sorted(e.name for e in entries)
    assert names == ["a.txt", "b.txt", "sub"]
    sub = next(e for e in entries if e.name == "sub")
    assert sub.is_dir is True


def test_list_dir_zip_subdir(tmp_path: Path) -> None:
    zp = _make_zip(
        tmp_path / "x.zip",
        {"sub/inner.txt": b"hello", "sub/deep/x.txt": b"x"},
    )
    fs = ArchiveFileSystem()
    entries = fs.list_dir(zp / "sub")
    names = sorted(e.name for e in entries)
    assert names == ["deep", "inner.txt"]


def test_list_dir_records_size_for_files(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"a.txt": b"abc"})
    fs = ArchiveFileSystem()
    entries = fs.list_dir(zp)
    a = next(e for e in entries if e.name == "a.txt")
    assert a.size == 3


def test_list_dir_tar(tmp_path: Path) -> None:
    tp = _make_tar(tmp_path / "x.tar", {"a.txt": b"a", "b.txt": b"bb"})
    fs = ArchiveFileSystem()
    entries = fs.list_dir(tp)
    assert sorted(e.name for e in entries) == ["a.txt", "b.txt"]


def test_list_dir_raises_for_non_archive(tmp_path: Path) -> None:
    plain = tmp_path / "notes.txt"
    plain.write_text("hi")
    fs = ArchiveFileSystem()
    with pytest.raises(ArchiveReadError):
        fs.list_dir(plain)


def test_list_dir_raises_for_corrupt_archive(tmp_path: Path) -> None:
    bogus = tmp_path / "broken.zip"
    bogus.write_bytes(b"not a real zip")
    fs = ArchiveFileSystem()
    with pytest.raises(ArchiveReadError):
        fs.list_dir(bogus)


# --- Extraction ----------------------------------------------------------------


def test_extract_entry_to_temp(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"a.txt": b"hello"})
    fs = ArchiveFileSystem()
    extracted = fs.extract_entry_to_temp(zp / "a.txt")
    assert extracted.exists()
    assert extracted.read_bytes() == b"hello"
    assert extracted.suffix == ".txt"
    extracted.unlink()


def test_extract_entry_to_destination(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"sub/inner.txt": b"world"})
    dst_dir = tmp_path / "out"
    dst_dir.mkdir()
    dst = dst_dir / "inner.txt"
    fs = ArchiveFileSystem()
    fs.extract_entry_to(zp / "sub" / "inner.txt", dst)
    assert dst.exists()
    assert dst.read_bytes() == b"world"


def test_extract_entry_raises_for_missing(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"a.txt": b"a"})
    fs = ArchiveFileSystem()
    with pytest.raises(ArchiveEntryNotFound):
        fs.extract_entry_to_temp(zp / "ghost.txt")


def test_extract_entry_to_temp_rejects_archive_root(tmp_path: Path) -> None:
    zp = _make_zip(tmp_path / "x.zip", {"a.txt": b"a"})
    fs = ArchiveFileSystem()
    with pytest.raises(ArchiveReadError):
        fs.extract_entry_to_temp(zp)
