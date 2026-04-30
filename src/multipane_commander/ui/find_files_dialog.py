"""Find Files dialog (SPEC §10.2).

v1 scope:
* Glob name pattern matched against each file/dir relative path.
* Optional substring content search (text only; binary files skipped;
  files larger than `_CONTENT_SIZE_LIMIT` skipped to keep the search
  responsive on a single thread).
* Result count capped at `_MAX_RESULTS` so the UI doesn't drown.
* Results list double-click navigates the active pane to the result.

Out of v1 scope (called out explicitly):
* "Feed to listbox" virtual-tab mode (SPEC §10.2 nice-to-have).
* Regex content search and encoding hints.
* Background threading (search is synchronous; the cap keeps it bounded).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

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


_MAX_RESULTS = 5_000
_CONTENT_SIZE_LIMIT = 10 * 1024 * 1024  # 10 MB


@dataclass(slots=True)
class FindResult:
    path: Path
    matched_content: bool


def find_files(
    root: Path,
    *,
    name_pattern: str = "*",
    content_query: str = "",
    recursive: bool = True,
    max_results: int = _MAX_RESULTS,
) -> list[FindResult]:
    """Search `root` for files matching `name_pattern` and (optionally)
    containing `content_query`.

    Pure function — public so tests don't need to spin up the dialog.
    """
    pattern = name_pattern or "*"
    iterator = root.rglob(pattern) if recursive else root.glob(pattern)

    results: list[FindResult] = []
    needle = content_query.lower()

    for candidate in iterator:
        if len(results) >= max_results:
            break
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue
        if not needle:
            results.append(FindResult(path=candidate, matched_content=False))
            continue
        try:
            if candidate.stat().st_size > _CONTENT_SIZE_LIMIT:
                continue
            with candidate.open("rb") as handle:
                head = handle.read(_CONTENT_SIZE_LIMIT)
            if b"\x00" in head[:8192]:
                continue  # likely binary
            text = head.decode("utf-8", errors="replace").lower()
        except OSError:
            continue
        if needle in text:
            results.append(FindResult(path=candidate, matched_content=True))
    return results


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
        close_button = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        search_button.clicked.connect(self._run_search)
        close_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self._name_input.setFocus()

    def _run_search(self) -> None:
        results = find_files(
            self._root,
            name_pattern=self._name_input.text().strip() or "*",
            content_query=self._content_input.text().strip(),
            recursive=self._recursive_checkbox.isChecked(),
        )
        self._results_list.clear()
        for result in results:
            item = QListWidgetItem(str(result.path.relative_to(self._root)))
            item.setData(Qt.ItemDataRole.UserRole, result.path)
            self._results_list.addItem(item)
        capped = len(results) >= _MAX_RESULTS
        suffix = f" (capped at {_MAX_RESULTS})" if capped else ""
        self._summary.setText(f"{len(results)} result(s){suffix}")

    def _activate_result(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(path, Path) and self._on_open is not None:
            self._on_open(path)
