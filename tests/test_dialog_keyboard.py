from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from multipane_commander.ui.dialogs import TextEntryDialog
from multipane_commander.ui.find_files_dialog import FindFilesDialog
from multipane_commander.ui.transfer_dialog import TransferDialog


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def test_transfer_dialog_enter_accepts_from_destination_field(tmp_path: Path) -> None:
    app = _qapp()
    source = tmp_path / "item.txt"
    source.write_text("content")
    destination = tmp_path / "dest"
    destination.mkdir()

    dialog = TransferDialog(
        operation="move",
        source_paths=[source],
        default_destination=destination,
    )
    dialog.show()
    dialog.destination_edit.setFocus()
    app.processEvents()

    QTest.keyClick(dialog.destination_edit, Qt.Key.Key_Return)
    app.processEvents()

    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()


def test_transfer_dialog_escape_rejects_from_destination_field(tmp_path: Path) -> None:
    app = _qapp()
    source = tmp_path / "item.txt"
    source.write_text("content")
    destination = tmp_path / "dest"
    destination.mkdir()

    dialog = TransferDialog(
        operation="move",
        source_paths=[source],
        default_destination=destination,
    )
    dialog.show()
    dialog.destination_edit.setFocus()
    app.processEvents()

    QTest.keyClick(dialog.destination_edit, Qt.Key.Key_Escape)
    app.processEvents()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not dialog.isVisible()
    dialog.close()


def test_text_entry_dialog_enter_accepts_from_input() -> None:
    app = _qapp()
    dialog = TextEntryDialog(
        parent=None,
        title="Rename Item",
        subtitle="Rename this item.",
        field_label="New name",
        initial_value="old.txt",
        accept_label="Rename",
    )
    dialog.show()
    dialog.input.setFocus()
    app.processEvents()

    QTest.keyClick(dialog.input, Qt.Key.Key_Return)
    app.processEvents()

    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()


def test_find_files_enter_on_result_still_opens_result(tmp_path: Path) -> None:
    app = _qapp()
    target = tmp_path / "match.txt"
    target.write_text("needle")
    opened: list[Path] = []

    dialog = FindFilesDialog(tmp_path, on_open=opened.append)
    dialog.show()
    dialog._name_input.setFocus()
    app.processEvents()

    QTest.keyClick(dialog._name_input, Qt.Key.Key_Return)
    app.processEvents()
    assert dialog._results_list.count() == 1

    dialog._results_list.setCurrentRow(0)
    dialog._results_list.setFocus()
    app.processEvents()

    QTest.keyClick(dialog._results_list, Qt.Key.Key_Return)
    app.processEvents()

    assert opened == [target]
    dialog.close()
