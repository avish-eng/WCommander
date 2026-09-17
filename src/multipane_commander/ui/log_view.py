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
)

from multipane_commander.services.jobs.model import JobLogEntry

_STATUS_LABELS = {
    "completed": "Completed",
    "completed_with_errors": "Completed with errors",
    "cancelled": "Cancelled",
}


class LogView(QFrame):
    """Session history of finished file operations, newest first."""

    clear_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("logView")

        self.title = QLabel("Log")
        self.title.setObjectName("logTitle")
        self.empty_label = QLabel("No finished actions yet.")
        self.empty_label.setObjectName("logEmpty")
        self.clear_button = QPushButton("Clear Log")
        self.clear_button.clicked.connect(self.clear_requested.emit)
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("logList")
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.clear_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.list_widget)

        self._update_empty_state()

    def add_entry(self, entry: JobLogEntry) -> None:
        self.list_widget.insertItem(0, self._build_item(entry))
        self._update_empty_state()

    def set_entries(self, entries: list[JobLogEntry]) -> None:
        self.list_widget.clear()
        for entry in entries:
            self.list_widget.addItem(self._build_item(entry))
        self._update_empty_state()

    @staticmethod
    def _build_item(entry: JobLogEntry) -> QListWidgetItem:
        operation = entry.operation.title() if entry.operation else "Operation"
        status = _STATUS_LABELS.get(entry.status, entry.status)
        stamp = entry.timestamp.strftime("%H:%M:%S")
        text = (
            f"[{stamp}] {operation} | {status} | "
            f"{entry.completed_actions} ok, {entry.total_actions} total | {entry.title}"
        )
        if entry.errors:
            text += f" | {len(entry.errors)} error(s)"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, entry.id)
        item.setToolTip("\n".join(entry.errors) if entry.errors else text)
        return item

    def _update_empty_state(self) -> None:
        has_items = self.list_widget.count() > 0
        self.empty_label.setVisible(not has_items)
        self.list_widget.setVisible(has_items)
