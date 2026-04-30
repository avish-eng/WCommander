from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

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

from multipane_commander.services.fs.local_fs import LocalFileSystem
from multipane_commander.services.jobs.model import FileJobAction, FileJobResult, FileJobSnapshot


class _FileJobWorker(QObject):
    progress_changed = Signal(int, int, str)
    finished = Signal(object)

    def __init__(self, actions: list[FileJobAction]) -> None:
        super().__init__()
        self.actions = actions
        self.fs = LocalFileSystem()
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def run(self) -> None:
        processed = 0
        completed = 0
        errors: list[str] = []

        for index, action in enumerate(self.actions, start=1):
            if self.cancel_requested:
                self.finished.emit(
                    FileJobResult(
                        completed_actions=completed,
                        processed_actions=processed,
                        cancelled=True,
                        errors=errors,
                    )
                )
                return

            try:
                if action.operation in {"copy", "move"} and action.destination is not None:
                    if action.destination.exists() and not action.replace_existing:
                        errors.append(
                            f"{action.source} -> {action.destination}: destination already exists"
                        )
                        processed = index
                        self.progress_changed.emit(
                            index,
                            len(self.actions),
                            f"Skipped {action.source.name}",
                        )
                        continue

                    if action.replace_existing and action.destination.exists():
                        self.fs.replace_entry(
                            action.source,
                            action.destination,
                            operation=action.operation,
                        )
                    elif action.operation == "copy":
                        self.fs.copy_entry(action.source, action.destination)
                    else:
                        self.fs.move_entry(action.source, action.destination)
                    label = f"{action.source.name} -> {action.destination}"
                elif action.operation == "delete":
                    self.fs.delete_entry(action.source, bypass_trash=action.bypass_trash)
                    label = (
                        f"Permanently deleted {action.source}"
                        if action.bypass_trash
                        else f"Deleted {action.source}"
                    )
                else:
                    errors.append(f"Unsupported action: {action}")
                    processed = index
                    self.progress_changed.emit(
                        index,
                        len(self.actions),
                        f"Skipped {action.source.name}",
                    )
                    continue
            except Exception as exc:
                target = (
                    action.destination
                    if action.destination is not None
                    else action.source
                )
                errors.append(f"{action.source} -> {target}: {exc}")
                processed = index
                self.progress_changed.emit(
                    index,
                    len(self.actions),
                    f"Failed {action.source.name}",
                )
                continue

            processed = index
            completed += 1
            self.progress_changed.emit(index, len(self.actions), label)

        self.finished.emit(
            FileJobResult(
                completed_actions=completed,
                processed_actions=processed,
                cancelled=False,
                errors=errors,
            )
        )


class _JobEventBridge(QObject):
    progress_marshaled = Signal(int, int, str)
    finished_marshaled = Signal(object)

    @Slot(int, int, str)
    def forward_progress(self, current: int, total: int, label: str) -> None:
        self.progress_marshaled.emit(current, total, label)

    @Slot(object)
    def forward_finished(self, result: FileJobResult) -> None:
        self.finished_marshaled.emit(result)


class JobManager(QObject):
    job_changed = Signal(object)
    job_removed = Signal(str)

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
            current_snapshot.status = "running"
            progress.update_progress(current, total, label)
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
            on_finished(result)
            thread.quit()

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
            worker.deleteLater()
            thread.deleteLater()
            if thread in self._active_threads:
                self._active_threads.remove(thread)
            self._active_workers.pop(snapshot.id, None)
            self._event_bridges.pop(snapshot.id, None)

        thread.started.connect(worker.run)
        worker.progress_changed.connect(bridge.forward_progress)
        worker.finished.connect(bridge.forward_finished)
        bridge.progress_marshaled.connect(update_progress)
        bridge.finished_marshaled.connect(finish_job)
        thread.finished.connect(cleanup_job)
        progress.cancel_requested.connect(worker.cancel)
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

    def update_progress(self, current: int, total: int, label: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.label.setText(label)

    def finish(self, snapshot: FileJobSnapshot) -> None:
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
        if not self.isVisible():
            self.show()

    def _dismiss(self) -> None:
        self.dismiss_requested.emit()
        self.close()
