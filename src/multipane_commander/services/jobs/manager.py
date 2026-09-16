from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from multipane_commander.services.fs.local_fs import OperationCancelled
from multipane_commander.services.jobs.transfer import TransferExecutor
from multipane_commander.services.jobs.model import FileJobAction, FileJobResult, FileJobSnapshot
from multipane_commander.ui.dialog_keys import install_dialog_key_bindings


class _FileJobWorker(QObject):
    progress_changed = Signal(int, int, str)
    transfer_changed = Signal(object)
    finished = Signal(object)

    def __init__(self, actions: list[FileJobAction]) -> None:
        super().__init__()
        self.actions = actions
        self._cancelled = Event()
        self.executor = TransferExecutor(self._cancelled, self.transfer_changed.emit)
        self.fs = self.executor.fs
        self.archive_fs = self.executor.archive

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        result = FileJobResult(completed_actions=0)
        for index, action in enumerate(self.actions, start=1):
            try:
                self.executor.execute(action)
            except OperationCancelled:
                result.cancelled = True
                break
            except Exception as exc:
                result.errors.append(f"{action.source} -> {action.destination or action.source}: {exc}")
                label = f"Failed {action.source.name}"
            else:
                result.completed_actions += 1
                result.successful_actions.append(action)
                label = f"Completed {action.source.name}"
            result.processed_actions = index
            self.progress_changed.emit(index, len(self.actions), label)
        self.finished.emit(result)


class _JobEventBridge(QObject):
    progress_marshaled = Signal(int, int, str)
    finished_marshaled = Signal(object)
    transfer_marshaled = Signal(object)

    @Slot(object)
    def forward_transfer(self, progress) -> None:
        self.transfer_marshaled.emit(progress)

    @Slot(int, int, str)
    def forward_progress(self, current: int, total: int, label: str) -> None:
        self.progress_marshaled.emit(current, total, label)

    @Slot(object)
    def forward_finished(self, result: FileJobResult) -> None:
        self.finished_marshaled.emit(result)


class JobManager(QObject):
    job_changed = Signal(object)
    job_removed = Signal(str)
    idle = Signal()

    def cancel_all(self) -> None:
        for worker in self._active_workers.values():
            worker.cancel()

    def has_active_jobs(self) -> bool:
        return bool(self._active_threads)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active_threads: list[QThread] = []
        self._active_workers: dict[str, _FileJobWorker] = {}
        self._event_bridges: dict[str, _JobEventBridge] = {}
        self._snapshots: dict[str, FileJobSnapshot] = {}
        self._progress_dialogs: dict[str, "_JobProgressDialog"] = {}

    def snapshots(self) -> list[FileJobSnapshot]:
        return list(self._snapshots.values())

    def cancel_job(self, job_id: str) -> None:
        worker = self._active_workers.get(job_id)
        if worker is not None:
            worker.cancel()
            snapshot = self._snapshots[job_id]
            snapshot.status = "cancelling"
            snapshot.current_label = "Cancelling…"
            self.job_changed.emit(replace(snapshot))
            dialog = self._progress_dialogs.get(job_id)
            if dialog is not None:
                dialog.label.setText("Cancelling…")
                dialog.cancel_button.setEnabled(False)

    def start_file_job(
        self,
        *,
        parent: QWidget,
        title: str,
        actions: list[FileJobAction],
        on_finished: Callable[[FileJobResult], None],
    ) -> None:
        if not actions:
            return

        snapshot = FileJobSnapshot(
            title=title,
            total_actions=len(actions),
            status="running",
            current_label="Starting...",
        )
        self._snapshots[snapshot.id] = snapshot
        self.job_changed.emit(replace(snapshot))

        worker = _FileJobWorker(actions)
        thread = QThread(self)
        bridge = _JobEventBridge(self)
        worker.moveToThread(thread)
        self._active_workers[snapshot.id] = worker
        self._event_bridges[snapshot.id] = bridge

        progress = _JobProgressDialog(title=title, parent=parent)
        self._progress_dialogs[snapshot.id] = progress

        def update_progress(current: int, total: int, label: str) -> None:
            current_snapshot = self._snapshots[snapshot.id]
            current_snapshot.processed_actions = current
            current_snapshot.total_actions = total
            current_snapshot.current_label = label
            if current_snapshot.status != "cancelling":
                current_snapshot.status = "running"
            progress.update_progress(current, total, label)
            self.job_changed.emit(replace(current_snapshot))

        def update_transfer(transfer) -> None:
            current_snapshot = self._snapshots[snapshot.id]
            current_snapshot.transfer = transfer
            progress.update_transfer(transfer)
            self.job_changed.emit(replace(current_snapshot))

        def finish_job(result: FileJobResult) -> None:
            current_snapshot = self._snapshots[snapshot.id]
            current_snapshot.completed_actions = result.completed_actions
            current_snapshot.processed_actions = result.processed_actions
            current_snapshot.errors = result.errors
            if result.cancelled:
                current_snapshot.status = "cancelled"
                current_snapshot.current_label = "Cancelled"
            elif result.errors:
                current_snapshot.status = "completed_with_errors"
                current_snapshot.current_label = "Completed with errors"
            else:
                current_snapshot.status = "completed"
                current_snapshot.current_label = "Completed"

            progress.finish(current_snapshot)
            self.job_changed.emit(replace(current_snapshot))
            thread.quit()
            on_finished(result)

        def dismiss_finished_job() -> None:
            self._progress_dialogs.pop(snapshot.id, None)
            if snapshot.id in self._snapshots and self._snapshots[snapshot.id].status in {
                "completed",
                "completed_with_errors",
                "cancelled",
            }:
                self._snapshots.pop(snapshot.id, None)
                self.job_removed.emit(snapshot.id)

        def cleanup_job() -> None:
            thread.deleteLater()
            if thread in self._active_threads:
                self._active_threads.remove(thread)
            self._active_workers.pop(snapshot.id, None)
            self._event_bridges.pop(snapshot.id, None)
            bridge.deleteLater()
            if not self._active_threads:
                self.idle.emit()

        thread.started.connect(worker.run)
        worker.progress_changed.connect(bridge.forward_progress)
        worker.finished.connect(bridge.forward_finished)
        thread.finished.connect(worker.deleteLater)
        worker.transfer_changed.connect(bridge.forward_transfer)
        bridge.transfer_marshaled.connect(update_transfer)
        bridge.progress_marshaled.connect(update_progress)
        bridge.finished_marshaled.connect(finish_job)
        thread.finished.connect(cleanup_job)
        progress.cancel_requested.connect(lambda: self.cancel_job(snapshot.id))
        progress.dismiss_requested.connect(dismiss_finished_job)

        self._active_threads.append(thread)
        thread.start()
        progress.show()


class _JobProgressDialog(QDialog):
    cancel_requested = Signal()
    dismiss_requested = Signal()

    def __init__(self, *, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.resize(560, 190)

        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        subtitle_label = QLabel(
            "This transfer runs in the background and can stay open while you keep working."
        )
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setWordWrap(True)

        self.label = QLabel("Starting...")
        self.label.setObjectName("dialogSectionLabel")
        self.transfer_label = QLabel()
        self.transfer_label.setWordWrap(True)
        self.byte_progress = QProgressBar()
        self.byte_progress.hide()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setValue(0)
        self.cancel_button = QPushButton("Cancel")
        self.background_button = QPushButton("Move To Background")
        self.cancel_button.setProperty("dialogRole", "secondary")
        self.background_button.setProperty("dialogRole", "primary")
        self.background_button.setDefault(True)
        self.background_button.setAutoDefault(True)
        self.cancel_button.setAutoDefault(False)

        card = QFrame()
        card.setObjectName("dialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)
        card_layout.addWidget(self.label)
        card_layout.addWidget(self.progress_bar)
        card_layout.addWidget(self.transfer_label)
        card_layout.addWidget(self.byte_progress)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.background_button)
        button_row.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addWidget(card)
        layout.addLayout(button_row)

        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.background_button.clicked.connect(self.hide)
        install_dialog_key_bindings(
            self,
            accept=self._activate_default_button,
            reject=self._close_from_keyboard,
        )

    def update_progress(self, current: int, total: int, label: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.label.setText(label)

    def update_transfer(self, transfer) -> None:
        self.transfer_label.setText(transfer.text)
        self.byte_progress.show()
        self.byte_progress.setRange(0, 1000 if transfer.bytes_total else 0)
        if transfer.bytes_total:
            self.byte_progress.setValue(min(1000, int(transfer.bytes_done * 1000 / transfer.bytes_total)))

    def finish(self, snapshot: FileJobSnapshot) -> None:
        self.cancel_button.setEnabled(True)
        self.byte_progress.setRange(0, 1000)
        self.progress_bar.setMaximum(max(snapshot.total_actions, 1))
        self.progress_bar.setValue(snapshot.processed_actions)
        self.label.setText(snapshot.current_label)
        self.background_button.setVisible(False)
        self.cancel_button.setText("Close")
        self.cancel_button.setProperty("dialogRole", "primary")
        self.cancel_button.setDefault(True)
        self.cancel_button.setAutoDefault(True)
        self.cancel_button.clicked.disconnect()
        self.cancel_button.clicked.connect(self._dismiss)
        if not self.isVisible() and snapshot.status == "completed_with_errors":
            self.show()

    def _activate_default_button(self) -> None:
        if self.background_button.isVisible():
            self.background_button.click()
            return
        self.cancel_button.click()

    def _close_from_keyboard(self) -> None:
        if self.background_button.isVisible():
            self.background_button.click()
            return
        self.cancel_button.click()

    def _dismiss(self) -> None:
        self.dismiss_requested.emit()
        self.close()
