from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView, QMessageBox

from multipane_commander.services.ai import AiResult, PaneRoots
from multipane_commander.services.jobs.manager import _JobProgressDialog
from multipane_commander.services.jobs.model import FileJobSnapshot
from multipane_commander.ui.ai_palette import AiPaletteDialog
from multipane_commander.ui.dialogs import ask_confirmation
from multipane_commander.ui.multi_rename_dialog import MultiRenameDialog
from multipane_commander.ui.theme_editor import ThemeEditorDialog
from multipane_commander.ui.themes import builtin_themes, build_stylesheet
from multipane_commander.ui.transfer_dialog import TransferDialog


@pytest.fixture
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    for window in application.topLevelWidgets():
        window.close()
    application.processEvents()


def test_transfer_rejects_blank_and_missing_destination_and_retains_input(app, tmp_path):
    dialog = TransferDialog(operation="copy", source_paths=[tmp_path / "a.txt"],
                            default_destination=tmp_path)
    dialog.show()
    for value in ("", "   ", "missing"):
        dialog.destination_edit.setText(value)
        dialog.destination_edit.setFocus()
        app.processEvents()
        QTest.keyClick(dialog.destination_edit, Qt.Key.Key_Return)
        assert dialog.isVisible()
        assert dialog._validation.isVisible()
        assert dialog.destination_edit.text() == value
    target = tmp_path / "target"
    target.mkdir()
    dialog.destination_edit.setText("target")
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.destination_directory() == target


def test_rename_preview_is_read_only_and_invalid_names_prevent_acceptance(app, tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("original")
    dialog = MultiRenameDialog([source])
    dialog.show()
    assert dialog._preview_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    dialog._name_input.setText("a/b")
    assert dialog.previews()[0].error
    assert not dialog._rename_button.isEnabled()
    dialog.accept()
    assert dialog.isVisible()
    dialog._ext_input.clear()
    dialog._name_input.clear()
    assert dialog.previews()[0].error
    dialog._name_input.setText("renamed")
    assert dialog._rename_button.isEnabled()
    assert dialog.previews()[0].target.name == "renamed"
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert source.read_text() == "original"


def test_rename_duplicate_destinations_mark_all_rows_and_block_acceptance(app, tmp_path):
    paths = [tmp_path / "a.txt", tmp_path / "b.txt"]
    for path in paths:
        path.write_text(path.name)
    dialog = MultiRenameDialog(paths)
    dialog._name_input.setText("same")
    assert all(preview.collision for preview in dialog.previews())
    assert not dialog._rename_button.isEnabled()


class _Runner(QObject):
    event = Signal(object)
    session_done = Signal(object)

    def __init__(self):
        super().__init__()
        self.cancelled = []
        self.started = 0

    def start_session(self, **kwargs):
        self.started += 1
        return f"request-{self.started}"

    def cancel(self, session_id):
        self.cancelled.append(session_id)


@pytest.mark.parametrize("close_method", ["reject", "close"])
def test_ai_palette_can_send_after_closing_active_request(app, tmp_path, close_method):
    runner = _Runner()
    dialog = AiPaletteDialog(runner, PaneRoots(left=tmp_path, right=tmp_path))
    dialog.show_and_focus()
    dialog._input.setText("question")
    dialog._send()
    getattr(dialog, close_method)()
    runner.session_done.emit(AiResult(session_id="request-1", status="cancelled", text="", tool_calls=[]))
    dialog.show_and_focus()
    assert runner.cancelled == ["request-1"]
    assert dialog._send_btn.isEnabled()
    assert not dialog._spinner.isVisible()
    assert not dialog._cancel_btn.isVisible()
    dialog._send_btn.click()
    assert runner.started == 2


def _theme_dialog():
    themes = builtin_themes()
    return ThemeEditorDialog(parent=None, initial_theme=themes[0],
                             available_themes=themes, selected_theme_id=themes[0].id)


def test_theme_invalid_color_keeps_editor_open_and_can_be_corrected(app):
    dialog = _theme_dialog()
    dialog.show()
    original = dialog._fields["accent"].text()
    dialog._fields["accent"].setText("not-a-color")
    dialog.accept()
    assert dialog.isVisible()
    assert dialog._validation.isVisible()
    assert dialog._fields["accent"].text() == "not-a-color"
    dialog._fields["accent"].setText(original)
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted


def test_theme_cancel_discards_default_and_delete_without_backup(app, monkeypatch):
    dialog = _theme_dialog()
    mutations = []
    dialog.default_theme_requested.connect(mutations.append)
    dialog.delete_theme_requested.connect(mutations.append)
    monkeypatch.setattr("multipane_commander.ui.theme_editor.ask_confirmation", lambda **kwargs: True)
    monkeypatch.setattr("multipane_commander.ui.theme_editor.backup_theme_definition", mutations.append)
    dialog.theme_choice.setCurrentIndex(1)
    dialog.make_default_button.click()
    dialog.delete_theme_button.click()
    dialog.reject()
    assert mutations == []


def test_theme_form_scrolls_while_save_remains_visible(app):
    dialog = _theme_dialog()
    dialog.setFont(QFont("Segoe UI", 10))
    dialog.setStyleSheet(build_stylesheet(builtin_themes()[0]))
    dialog.resize(720, 600)
    dialog.show()
    app.processEvents()
    assert dialog.height() <= 600
    assert dialog._scroll.verticalScrollBar().maximum() > 0
    position = dialog._save_button.mapTo(dialog, dialog._save_button.rect().bottomRight())
    assert dialog.rect().contains(position)


def test_destructive_confirmation_enter_keeps_items(app):
    seen = []

    def press_enter():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        seen.append(dialog.defaultButton().text())
        QTest.keyClick(dialog, Qt.Key.Key_Return)

    QTimer.singleShot(0, press_enter)
    accepted = ask_confirmation(parent=None, title="Delete", message="Delete permanently?",
                                accept_label="Delete", cancel_label="Keep Items", is_destructive=True)
    assert seen == ["Keep Items"]
    assert not accepted


@pytest.mark.parametrize("status, visible", [("completed", False), ("completed_with_errors", True)])
def test_background_job_only_reopens_for_errors(app, status, visible):
    dialog = _JobProgressDialog(title="Copy")
    dialog.show()
    dialog.background_button.click()
    assert not dialog.isVisible()
    dialog.finish(FileJobSnapshot(title="Copy", total_actions=1, processed_actions=1,
                                  completed_actions=1, status=status, current_label="Finished"))
    assert dialog.isVisible() is visible
