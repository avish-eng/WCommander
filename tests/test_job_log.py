from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui_wait import wait_until
from PySide6.QtWidgets import QApplication

from multipane_commander.services.jobs.log import MAX_LOG_ENTRIES, JobLog
from multipane_commander.services.jobs.manager import JobManager, _JobProgressDialog
from multipane_commander.services.jobs.model import (
    FileJobAction,
    FileJobSnapshot,
    JobLogEntry,
)
from multipane_commander.ui.log_view import LogView


_APP: QApplication | None = None
_DIALOGS: list[_JobProgressDialog] = []


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def test_job_log_keeps_newest_first_and_signals() -> None:
    log = JobLog()
    added: list[JobLogEntry] = []
    changed: list[bool] = []
    log.entry_added.connect(added.append)
    log.entries_changed.connect(lambda: changed.append(True))

    first = JobLogEntry(operation="copy", title="Copy 1", completed_actions=1, total_actions=1)
    second = JobLogEntry(operation="move", title="Move 1", completed_actions=1, total_actions=1)
    log.add_entry(first)
    log.add_entry(second)

    assert [entry.title for entry in log.entries()] == ["Move 1", "Copy 1"]
    assert added == [first, second]
    assert len(changed) == 2


def test_job_log_caps_entries_and_counts_errors() -> None:
    log = JobLog()

    for index in range(MAX_LOG_ENTRIES + 25):
        log.add_entry(JobLogEntry(title=f"Job {index}", errors=["boom"] if index == 0 else []))

    entries = log.entries()
    assert len(entries) == MAX_LOG_ENTRIES
    assert entries[0].title == f"Job {MAX_LOG_ENTRIES + 24}"
    assert entries[-1].title == "Job 25"
    assert log.error_count() == 0


def test_job_log_error_count_and_clear() -> None:
    log = JobLog()
    log.add_entry(JobLogEntry(title="Broken", errors=["a", "b"]))
    assert log.error_count() == 2

    log.clear()
    assert log.entries() == []
    log.clear()  # no-op, no signal crash
    assert log.entries() == []


def test_log_view_renders_entries_and_empty_state() -> None:
    _qapp()
    view = LogView()
    assert view.empty_label.isVisible() or not view.isVisible()

    view.add_entry(
        JobLogEntry(
            operation="copy",
            title="Copy 2 item(s) -> C:\\dst",
            status="completed",
            completed_actions=2,
            total_actions=2,
        )
    )
    assert view.list_widget.count() == 1
    text = view.list_widget.item(0).text()
    assert "Copy" in text
    assert "Completed" in text
    assert "2 ok, 2 total" in text

    error_entry = JobLogEntry(
        operation="delete",
        title="Delete 3 item(s)",
        status="completed_with_errors",
        completed_actions=2,
        total_actions=3,
        errors=["permission denied"],
    )
    view.add_entry(error_entry)
    assert view.list_widget.count() == 2
    assert "1 error(s)" in view.list_widget.item(0).text()
    assert view.list_widget.item(0).toolTip() == "permission denied"

    view.set_entries([])
    assert view.list_widget.count() == 0


def test_log_view_clear_button_emits() -> None:
    _qapp()
    view = LogView()
    requested: list[bool] = []
    view.clear_requested.connect(lambda: requested.append(True))

    view.clear_button.click()

    assert requested == [True]


def test_progress_dialog_auto_closes_on_clean_finish() -> None:
    _qapp()
    dialog = _JobProgressDialog(title="Copy")
    _DIALOGS.append(dialog)
    dismissed: list[bool] = []
    dialog.dismiss_requested.connect(lambda: dismissed.append(True))
    try:
        dialog.show()

        dialog.finish(
            FileJobSnapshot(
                title="Copy",
                total_actions=1,
                completed_actions=1,
                processed_actions=1,
                status="completed",
                current_label="Completed",
            )
        )

        assert not dialog.isVisible()
        assert dismissed == [True]
    finally:
        dialog.close()
        _qapp().processEvents()


def test_progress_dialog_stays_open_with_error_details() -> None:
    _qapp()
    dialog = _JobProgressDialog(title="Move")
    _DIALOGS.append(dialog)
    dialog.show()
    try:
        dialog.finish(
            FileJobSnapshot(
                title="Move",
                total_actions=2,
                completed_actions=1,
                processed_actions=2,
                status="completed_with_errors",
                current_label="Completed with errors",
                errors=["move failed: locked"],
            )
        )

        assert dialog.isVisible()
        assert dialog.details_label.isVisible()
        assert "locked" in dialog.details_label.text()
    finally:
        dialog.close()
        _qapp().processEvents()


def test_job_manager_emits_log_entry_for_finished_transfer(tmp_path: Path) -> None:
    _qapp()
    source = tmp_path / "source.txt"
    source.write_text("payload")
    destination = tmp_path / "destination.txt"

    manager = JobManager()
    logged: list[JobLogEntry] = []
    manager.job_logged.connect(logged.append)

    manager.start_file_job(
        parent=None,
        title="Copy 1 item(s)",
        actions=[FileJobAction("copy", source, destination, replace_existing=True)],
        on_finished=lambda _result: None,
    )
    wait_until(lambda: bool(logged) and not manager.has_active_jobs())
    for _ in range(10):
        _qapp().processEvents()

    assert destination.read_text() == "payload"
    assert logged[0].operation == "copy"
    assert logged[0].status == "completed"
    assert logged[0].completed_actions == 1
    assert logged[0].total_actions == 1


def test_main_window_log_button_and_view(tmp_path: Path, monkeypatch) -> None:
    _qapp()
    from test_deep_integration import _make_window, _patch_terminals

    _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        active_button = window._active_pane().log_button
        assert active_button.text() == "Log"
        assert active_button.isVisible()
        assert not window.pane_views[1].log_button.isVisible()
        assert not window.log_view.isVisible()

        window.job_manager.job_logged.emit(
            JobLogEntry(operation="copy", title="Copy", completed_actions=1, total_actions=1)
        )
        assert window.log_view.list_widget.count() == 1
        assert active_button.text() == "Log (1)"
        assert active_button.property("hasErrors") is False

        window.job_manager.job_logged.emit(
            JobLogEntry(operation="move", title="Move", errors=["nope"], total_actions=1)
        )
        assert active_button.text() == "Log (2)"
        assert active_button.property("hasErrors") is True

        active_button.click()
        assert window.log_view.isVisible()
        assert active_button.text() == "Log"
        assert active_button.property("hasErrors") is False

        window.log_view.clear_button.click()
        assert window.log_view.list_widget.count() == 0

        window._set_active_pane(1)
        assert not window.pane_views[0].log_button.isVisible()
        assert window.pane_views[1].log_button.isVisible()
    finally:
        window.close()