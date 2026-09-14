"""Cancellable file search with streamed results and keyboard navigation.

Name patterns use glob syntax. Content search skips binaries and files over
10 MiB. Results are capped at 5,000; Stop keeps results already received.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from multipane_commander.ui.dialog_keys import install_dialog_key_bindings


from multipane_commander.services.background import BackgroundTasks
from multipane_commander.services.search import (  # compatibility for existing callers
    MAX_RESULTS as _MAX_RESULTS,
    CONTENT_SIZE_LIMIT as _CONTENT_SIZE_LIMIT,
    FindResult,
    find_files,
)


class FindFilesDialog(QDialog):
    def __init__(
        self,
        root: Path,
        *,
        parent=None,
        on_open: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find Files")
        self._root = root
        self._on_open = on_open
        self._tasks = BackgroundTasks(self)
        self._tasks.batch.connect(self._search_batch)
        self._tasks.finished.connect(self._search_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel(f"Searching under: {root}"))

        form = QFormLayout()
        self._name_input = QLineEdit("*")
        self._content_input = QLineEdit()
        self._recursive_checkbox = QCheckBox("Recursive")
        self._recursive_checkbox.setChecked(True)
        form.addRow("Name pattern (glob)", self._name_input)
        form.addRow("Containing text (optional)", self._content_input)
        form.addRow("", self._recursive_checkbox)
        layout.addLayout(form)

        self._results_list = QListWidget()
        self._results_list.itemActivated.connect(self._activate_result)
        layout.addWidget(self._results_list, 1)

        self._summary = QLabel("")
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox()
        search_button = buttons.addButton("Search", QDialogButtonBox.ButtonRole.AcceptRole)
        self._search_button = search_button
        close_button = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        search_button.setDefault(True)
        search_button.setAutoDefault(True)
        close_button.setAutoDefault(False)
        search_button.clicked.connect(self._run_search)
        close_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self._name_input.returnPressed.connect(search_button.click)
        self._content_input.returnPressed.connect(search_button.click)
        self._name_input.setFocus()
        install_dialog_key_bindings(
            self,
            accept=search_button.click,
            ignore_accept_for=lambda widget: widget is self._results_list
            or self._results_list.isAncestorOf(widget),
        )

    def _run_search(self) -> None:
        if self._tasks.is_running("search"):
            self._tasks.cancel("search")
            self._search_button.setText("Search")
            self._summary.setText(f"Cancelled · {self._results_list.count()} result(s)")
            return
        self._results_list.clear()
        self._summary.setText("Searching…")
        self._search_button.setText("Stop")
        root = self._root
        options = dict(name_pattern=self._name_input.text().strip() or "*",
                       content_query=self._content_input.text().strip(),
                       recursive=self._recursive_checkbox.isChecked())
        self._tasks.submit("search", lambda token, publish: find_files(
            root, **options, cancelled=token, on_batch=publish))

    def _search_batch(self, key, results) -> None:
        for result in results:
            item = QListWidgetItem(str(result.path.relative_to(self._root)))
            item.setData(Qt.ItemDataRole.UserRole, result.path)
            self._results_list.addItem(item)
        self._summary.setText(f"Searching… {self._results_list.count()} result(s)")

    def _search_finished(self, key, results, error) -> None:
        self._search_button.setText("Search")
        if error:
            self._summary.setText(f"Search failed: {error}")
            return
        count = self._results_list.count()
        suffix = f" (capped at {_MAX_RESULTS})" if count >= _MAX_RESULTS else ""
        self._summary.setText(f"{count} result(s){suffix}")

    def done(self, result) -> None:
        self._tasks.cancel_all()
        super().done(result)

    def _activate_result(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(path, Path) and self._on_open is not None:
            self._on_open(path)

__all__ = ["FindFilesDialog", "FindResult", "find_files", "_CONTENT_SIZE_LIMIT"]
