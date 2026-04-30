"""Multi-rename dialog (SPEC §10.1).

v1 template grammar (a tight subset of TC's):
* `[N]`  — original filename without extension
* `[E]`  — extension (without leading dot)
* `[C]`  — running counter starting at 1
* `[C0n]` — running counter zero-padded to width n (e.g. `[C03]` → `001`)

Anything outside the brackets is literal. `%%` is not supported (no
escaping needed for the v1 token set).

The dialog shows a live preview table; commit applies each rename in
order and pushes a record onto the supplied UndoStack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


_COUNTER_RE = re.compile(r"\[C(?:0(\d+))?\]")


def render_template(template: str, *, name_no_ext: str, extension: str, counter: int) -> str:
    """Render a single filename from `template`.

    Public so tests can drive it without spinning up the dialog.
    """
    result = template.replace("[N]", name_no_ext).replace("[E]", extension)

    def _counter_sub(match: re.Match) -> str:
        width = match.group(1)
        if width:
            return f"{counter:0{int(width)}d}"
        return str(counter)

    return _COUNTER_RE.sub(_counter_sub, result)


@dataclass(slots=True)
class RenamePreview:
    source: Path
    target: Path
    collision: bool


def build_preview(
    sources: Sequence[Path],
    *,
    name_template: str,
    ext_template: str,
) -> list[RenamePreview]:
    new_paths: list[Path] = []
    used: set[Path] = set()
    for index, source in enumerate(sources, start=1):
        stem = source.stem
        ext = source.suffix.lstrip(".")
        new_stem = render_template(name_template, name_no_ext=stem, extension=ext, counter=index)
        new_ext = render_template(ext_template, name_no_ext=stem, extension=ext, counter=index)
        new_name = new_stem + (("." + new_ext) if new_ext else "")
        target = source.with_name(new_name)
        new_paths.append(target)
        used.add(target)
    previews: list[RenamePreview] = []
    seen: set[Path] = set()
    for source, target in zip(sources, new_paths):
        collision = target.exists() and target != source
        if target in seen:
            collision = True
        seen.add(target)
        previews.append(RenamePreview(source=source, target=target, collision=collision))
    return previews


class MultiRenameDialog(QDialog):
    def __init__(
        self,
        sources: Sequence[Path],
        *,
        parent=None,
        name_template_initial: str = "[N]",
        ext_template_initial: str = "[E]",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Multi-Rename")
        self._sources: list[Path] = list(sources)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        self._name_input = QLineEdit(name_template_initial)
        self._ext_input = QLineEdit(ext_template_initial)
        form.addRow("Name template", self._name_input)
        form.addRow("Extension template", self._ext_input)
        layout.addLayout(form)

        hint = QLabel("Tokens: [N] name (no ext), [E] extension, [C] counter, [C03] zero-padded counter.")
        hint_font = QFont(hint.font())
        hint_font.setItalic(True)
        hint.setFont(hint_font)
        layout.addWidget(hint)

        self._preview_table = QTableWidget(0, 3)
        self._preview_table.setHorizontalHeaderLabels(["Original", "New", "Status"])
        header = self._preview_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._preview_table.verticalHeader().setVisible(False)
        layout.addWidget(self._preview_table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Rename")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._name_input.textChanged.connect(self._refresh_preview)
        self._ext_input.textChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def previews(self) -> list[RenamePreview]:
        return build_preview(
            self._sources,
            name_template=self._name_input.text(),
            ext_template=self._ext_input.text(),
        )

    def _refresh_preview(self) -> None:
        previews = self.previews()
        self._preview_table.setRowCount(len(previews))
        for row, preview in enumerate(previews):
            original = QTableWidgetItem(preview.source.name)
            target = QTableWidgetItem(preview.target.name)
            status = QTableWidgetItem("collision" if preview.collision else "ok")
            if preview.collision:
                for cell in (original, target, status):
                    cell.setForeground(Qt.GlobalColor.red)
            self._preview_table.setItem(row, 0, original)
            self._preview_table.setItem(row, 1, target)
            self._preview_table.setItem(row, 2, status)


def apply_renames(
    previews: Sequence[RenamePreview],
    *,
    rename: Callable[[Path, Path], None],
    on_record: Callable[[Path, Path], None] | None = None,
) -> tuple[int, list[str]]:
    """Apply renames in order. Returns (succeeded, errors)."""
    succeeded = 0
    errors: list[str] = []
    for preview in previews:
        if preview.source == preview.target:
            continue
        if preview.collision:
            errors.append(f"Skipped {preview.source.name}: target collision")
            continue
        try:
            rename(preview.source, preview.target)
        except OSError as exc:
            errors.append(f"{preview.source.name}: {exc}")
            continue
        succeeded += 1
        if on_record is not None:
            on_record(preview.source, preview.target)
    return succeeded, errors
