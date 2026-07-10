from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl

from multipane_commander.ui.main_window import determine_drag_drop_operation
from multipane_commander.ui.pane_view import (
    PaneView,
    build_file_drag_mime_data,
    decode_file_drag_paths,
)


def test_outgoing_drag_advertises_standard_local_file_urls(tmp_path) -> None:
    first = tmp_path / "first file.txt"
    second = tmp_path / "second#file.png"

    mime_data = build_file_drag_mime_data([first, second])

    assert mime_data.hasUrls()
    assert mime_data.hasFormat("text/uri-list")
    assert mime_data.hasFormat(PaneView._DRAG_MIME_TYPE)
    assert [Path(url.toLocalFile()) for url in mime_data.urls()] == [first, second]


def test_standard_external_file_drag_paths_are_accepted(tmp_path) -> None:
    dragged_file = tmp_path / "from explorer.txt"
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(dragged_file))])

    assert decode_file_drag_paths(mime_data) == [dragged_file]


def test_drag_drop_defaults_to_move_on_same_drive(monkeypatch) -> None:
    monkeypatch.setattr(
        "multipane_commander.ui.main_window.same_filesystem",
        lambda left, right: True,
    )
    source_paths = [Path("/work/alpha.txt")]
    destination_dir = Path("/work/target")

    operation = determine_drag_drop_operation(
        source_paths,
        destination_dir,
        Qt.KeyboardModifier.NoModifier,
    )

    assert operation == "move"


def test_drag_drop_defaults_to_copy_across_drives(monkeypatch) -> None:
    monkeypatch.setattr(
        "multipane_commander.ui.main_window.same_filesystem",
        lambda left, right: False,
    )
    source_paths = [Path("/work/alpha.txt")]
    destination_dir = Path("/other/target")

    operation = determine_drag_drop_operation(
        source_paths,
        destination_dir,
        Qt.KeyboardModifier.NoModifier,
    )

    assert operation == "copy"


def test_drag_drop_modifiers_override_default() -> None:
    source_paths = [Path(r"C:\work\alpha.txt")]
    destination_dir = Path(r"C:\target")

    assert (
        determine_drag_drop_operation(
            source_paths,
            destination_dir,
            Qt.KeyboardModifier.ControlModifier,
        )
        == "copy"
    )
    assert (
        determine_drag_drop_operation(
            source_paths,
            destination_dir,
            Qt.KeyboardModifier.ShiftModifier,
        )
        == "move"
    )
