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
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from multipane_commander.ui.dialog_keys import install_dialog_key_bindings


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
    error: str = ""


def build_preview(
    sources: Sequence[Path],
    *,
    name_template: str,
    ext_template: str,
) -> list[RenamePreview]:
    previews: list[RenamePreview] = []
    targets: dict[Path, list[RenamePreview]] = {}
    for index, source in enumerate(sources, start=1):
        stem = source.stem
        ext = source.suffix.lstrip(".")
        new_stem = render_template(name_template, name_no_ext=stem, extension=ext, counter=index)
        new_ext = render_template(ext_template, name_no_ext=stem, extension=ext, counter=index)
        new_name = new_stem + (("." + new_ext) if new_ext else "")
        try:
            if not new_stem or new_name in {".", ".."}:
                raise ValueError("Enter a nonempty file name.")
            reserved = getattr(os.path, "isreserved", lambda name: (
                PureWindowsPath(name).is_reserved()
                or bool(re.search(r'[<>:"/\\|?*\x00-\x1f]', name))
                or name.endswith((".", " "))
            ))
            if "\x00" in new_name or (os.name == "nt" and reserved(new_name)):
                raise ValueError("The name contains characters or a name reserved by Windows.")
            target = source.with_name(new_name)
            preview = RenamePreview(source, target, target.exists() and target != source)
        except (ValueError, OSError) as error:
            preview = RenamePreview(source, source, False, str(error))
        previews.append(preview)
        if not preview.error:
            targets.setdefault(preview.target, []).append(preview)
    for duplicates in targets.values():
        if len(duplicates) > 1:
            for preview in duplicates:
                preview.collision = True
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
        self._preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._preview_table.setHorizontalHeaderLabels(["Original", "New", "Status"])
        header = self._preview_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._preview_table.verticalHeader().setVisible(False)
        layout.addWidget(self._preview_table, 1)
        self._validation = QLabel()
        self._validation.setWordWrap(True)
        layout.addWidget(self._validation)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        rename_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._rename_button = rename_button
        rename_button.setText("Rename")
        rename_button.setDefault(True)
        rename_button.setAutoDefault(True)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._name_input.textChanged.connect(self._refresh_preview)
        self._ext_input.textChanged.connect(self._refresh_preview)
        self._refresh_preview()
        install_dialog_key_bindings(self, accept=rename_button.click)

    def previews(self) -> list[RenamePreview]:
        return build_preview(
            self._sources,
            name_template=self._name_input.text(),
            ext_template=self._ext_input.text(),
        )

    def _refresh_preview(self) -> None:
        previews = self.previews()
        invalid = any(preview.error or preview.collision for preview in previews)
        self._rename_button.setEnabled(bool(previews) and not invalid)
        self._validation.setText("Resolve invalid names and collisions before renaming." if invalid else "")
        self._preview_table.setRowCount(len(previews))
        for row, preview in enumerate(previews):
            original = QTableWidgetItem(preview.source.name)
            target = QTableWidgetItem("Invalid name" if preview.error else preview.target.name)
            status = QTableWidgetItem("invalid name" if preview.error else ("collision" if preview.collision else "ok"))
            status.setToolTip(preview.error)
            if preview.collision or preview.error:
                for cell in (original, target, status):
                    cell.setForeground(Qt.GlobalColor.red)
            self._preview_table.setItem(row, 0, original)
            self._preview_table.setItem(row, 1, target)
            self._preview_table.setItem(row, 2, status)

    def accept(self) -> None:
        self._refresh_preview()
        if self._rename_button.isEnabled():
            super().accept()


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
        if preview.error:
            errors.append(f"Skipped {preview.source.name}: {preview.error}")
            continue
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
