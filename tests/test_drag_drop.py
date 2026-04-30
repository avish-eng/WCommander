from pathlib import Path

from PySide6.QtCore import Qt

from multipane_commander.ui.main_window import determine_drag_drop_operation


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
