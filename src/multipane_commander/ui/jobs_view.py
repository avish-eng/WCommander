from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multipane_commander.services.jobs.model import FileJobSnapshot


class JobsView(QFrame):
    cancel_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("jobsView")

        self.title = QLabel("Jobs")
        self.title.setObjectName("jobsTitle")
        self.empty_label = QLabel("No active or recent jobs.")
        self.empty_label.setObjectName("jobsEmpty")
        self.list_widget = QListWidget()
        self.cancel_button = QPushButton("Cancel Selected Job")
        self.cancel_button.clicked.connect(self._cancel_selected_job)

        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.list_widget)

        self._update_empty_state()

    def upsert_snapshot(self, snapshot: FileJobSnapshot) -> None:
        existing = self._find_item(snapshot.id)
        progress_text = (
            f"{snapshot.completed_actions} ok, "
            f"{snapshot.processed_actions}/{snapshot.total_actions} processed"
        )
        text = (
            f"[{snapshot.status}] {snapshot.title} | "
            f"{progress_text} | "
            f"{snapshot.current_label}"
        )
        if existing is None:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, snapshot.id)
            self.list_widget.insertItem(0, item)
        else:
            existing.setText(text)
        self._update_empty_state()

    def remove_snapshot(self, job_id: str) -> None:
        item = self._find_item(job_id)
        if item is None:
            return
        row = self.list_widget.row(item)
        self.list_widget.takeItem(row)
        self._update_empty_state()

    def _find_item(self, job_id: str) -> QListWidgetItem | None:
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == job_id:
                return item
        return None

    def _cancel_selected_job(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        job_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(job_id, str):
            self.cancel_requested.emit(job_id)

    def _update_empty_state(self) -> None:
        has_items = self.list_widget.count() > 0
        self.empty_label.setVisible(not has_items)
        self.list_widget.setVisible(has_items)
