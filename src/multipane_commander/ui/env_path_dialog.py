from __future__ import annotations

import sys
import logging
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from multipane_commander.services.env_path import (
    PathSnapshot,
    clean_entries,
    path_snapshot,
    path_entry_key,
    save_windows_path_entries,
    set_process_path_entries,
)
from multipane_commander.ui.dialog_keys import install_dialog_key_bindings
from multipane_commander.ui.dialogs import show_message


logger = logging.getLogger(__name__)


class PathEntryLineEdit(QLineEdit):
    focused = Signal()

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        super().focusInEvent(event)
        self.focused.emit()


class EnvPathDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget | None,
        snapshot: PathSnapshot | None = None,
        metadata: list[tuple[str, str]] | None = None,
        save_app_entries: Callable[[list[str], list[str], list[str]], None] | None = None,
        clear_app_entries: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("PATH")
        self.setModal(True)
        self.resize(780, 520)
        self._snapshot = snapshot or path_snapshot()
        self._metadata = metadata
        self._save_app_entries = save_app_entries
        self._clear_app_entries = clear_app_entries
        self.saved_to_process = False
        self.saved_to_windows = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("PATH")
        title.setObjectName("dialogTitle")

        self.table = QTableWidget(0, 2)
        self.table.setObjectName("pathEntriesTable")
        self.table.setHorizontalHeaderLabels(["Path entry", "Saved in"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 110)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        add_button = QPushButton("Add")
        remove_button = QPushButton("Remove")
        up_button = QPushButton("Up")
        down_button = QPushButton("Down")
        for button in (add_button, remove_button, up_button, down_button):
            button.setObjectName("secondaryActionButton")
            edit_row.addWidget(button)
        edit_row.addStretch(1)

        add_button.clicked.connect(self._add_entry)
        remove_button.clicked.connect(self._remove_selected)
        up_button.clicked.connect(lambda: self._move_selected(-1))
        down_button.clicked.connect(lambda: self._move_selected(1))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save_button = QPushButton("Save in App")
        save_windows_button = QPushButton("Save to Windows")
        save_button.setProperty("dialogRole", "primary")
        save_windows_button.setProperty("dialogRole", "primary")
        save_button.setDefault(True)
        save_button.setAutoDefault(True)
        buttons.addButton(save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(save_windows_button, QDialogButtonBox.ButtonRole.ApplyRole)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setProperty("dialogRole", "secondary")
            cancel_button.setAutoDefault(False)

        save_button.clicked.connect(self._save_process)
        save_windows_button.clicked.connect(self._save_windows)
        buttons.rejected.connect(self.reject)
        save_windows_button.setEnabled(sys.platform == "win32")

        layout.addWidget(title)
        layout.addWidget(self.table, 1)
        layout.addLayout(edit_row)
        layout.addWidget(buttons)

        self._set_entries(self._snapshot.process_entries, self._metadata or self._infer_row_metadata())
        install_dialog_key_bindings(self, accept=save_button.click)

    def entries(self) -> list[str]:
        return clean_entries(
            [
                self._row_text(row)
                for row in range(self.table.rowCount())
            ]
        )

    def sources(self) -> list[str]:
        return [
            self._row_source(row)
            for row in range(self.table.rowCount())
            if self._row_text(row).strip()
        ]

    def original_entries(self) -> list[str]:
        return [
            self._row_original(row)
            for row in range(self.table.rowCount())
            if self._row_text(row).strip()
        ]

    def row_modified(self) -> list[bool]:
        return [
            self._row_modified(row)
            for row in range(self.table.rowCount())
            if self._row_text(row).strip()
        ]

    def _set_entries(self, entries: list[str], metadata: list[tuple[str, str]] | None = None) -> None:
        self.table.setRowCount(0)
        row_metadata = metadata or []
        for index, entry in enumerate(entries):
            source, original_entry = ("user", entry)
            if index < len(row_metadata):
                source, original_entry = row_metadata[index]
            self._append_row(entry, source, original_entry)
        if self.table.rowCount() == 0:
            self._append_row("", "user", "")
        self.table.selectRow(0)

    def _append_row(self, value: str, source: str = "user", original_entry: str | None = None) -> None:
        row = self.table.rowCount()
        self._insert_row(row, value, source, original_entry)

    def _insert_row(self, row: int, value: str, source: str = "user", original_entry: str | None = None) -> None:
        self.table.insertRow(row)
        editor = PathEntryLineEdit(value)
        editor.setObjectName("pathEntryInput")
        editor.setClearButtonEnabled(True)
        editor.setFrame(False)
        editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        editor.focused.connect(lambda editor=editor: self._select_editor_row(editor))
        self.table.setCellWidget(row, 0, editor)
        source_label = QLabel(self._source_label(source))
        source_label.setObjectName("pathEntrySource")
        source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        source_label.setProperty("pathSource", source)
        source_label.setProperty("originalPathEntry", original_entry or "")
        source_label.setProperty("initialDisplayPathEntry", value)
        self.table.setCellWidget(row, 1, source_label)

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return max(0, self.table.currentRow())
        return rows[0].row()

    def _add_entry(self) -> None:
        row = self._selected_row()
        insert_at = min(self.table.rowCount(), row + 1)
        self._insert_row(insert_at, "", "user", "")
        self.table.selectRow(insert_at)
        editor = self.table.cellWidget(insert_at, 0)
        if isinstance(editor, QLineEdit):
            editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def _remove_selected(self) -> None:
        if self.table.rowCount() <= 1:
            self._set_row_text(0, "")
            self._set_row_source(0, "user")
            self._set_row_original(0, "")
            self._set_row_initial_display(0, "")
            return
        row = self._selected_row()
        self.table.removeRow(row)
        self.table.selectRow(min(row, self.table.rowCount() - 1))

    def _move_selected(self, delta: int) -> None:
        row = self._selected_row()
        target = row + delta
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        current = self._row_text(row)
        current_source = self._row_source(row)
        current_original = self._row_original(row)
        current_initial = self._row_initial_display(row)
        other = self._row_text(target)
        other_source = self._row_source(target)
        other_original = self._row_original(target)
        other_initial = self._row_initial_display(target)
        self._set_row_text(row, other)
        self._set_row_source(row, other_source)
        self._set_row_original(row, other_original)
        self._set_row_initial_display(row, other_initial)
        self._set_row_text(target, current)
        self._set_row_source(target, current_source)
        self._set_row_original(target, current_original)
        self._set_row_initial_display(target, current_initial)
        self.table.selectRow(target)

    def _save_process(self) -> None:
        entries = self.entries()
        sources = self.sources()
        original_entries = self.original_entries()
        row_modified = self.row_modified()
        logger.info(
            "PATH Save in App clicked: entries=%s sources=%s original_entries=%s row_modified=%s",
            entries,
            sources,
            original_entries,
            row_modified,
        )
        try:
            set_process_path_entries(entries)
            if self._save_app_entries is not None:
                self._save_app_entries(entries, sources, original_entries)
            else:
                logger.warning("PATH Save in App has no app persistence callback")
        except OSError as exc:
            logger.exception("PATH Save in App failed")
            show_message(
                parent=self,
                title="PATH not saved",
                message=str(exc),
                level="error",
            )
            return
        self.saved_to_process = True
        self.accept()

    def _save_windows(self) -> None:
        entries = self.entries()
        sources = self.sources()
        original_entries = self.original_entries()
        row_modified = self.row_modified()
        logger.info(
            "PATH Save to Windows clicked: entries=%s sources=%s original_entries=%s "
            "row_modified=%s snapshot_machine=%s",
            entries,
            sources,
            original_entries,
            row_modified,
            self._snapshot.machine_entries,
        )
        try:
            result = save_windows_path_entries(
                entries,
                sources,
                original_machine_entries=self._snapshot.machine_entries,
                original_entries=original_entries,
                row_modified=row_modified,
            )
        except PermissionError:
            logger.exception("PATH Save to Windows failed: permission denied")
            show_message(
                parent=self,
                title="PATH not saved",
                message=(
                    "Editing machine PATH entries requires running the app as Administrator. "
                    "Reopen the app as Administrator, then use Save to Windows again."
                ),
                level="error",
            )
            return
        except OSError as exc:
            logger.exception("PATH Save to Windows failed")
            show_message(
                parent=self,
                title="PATH not saved",
                message=str(exc),
                level="error",
            )
            return
        self.saved_to_process = True
        self.saved_to_windows = True
        logger.info(
            "PATH Save to Windows completed: user_entries=%s machine_entries=%s "
            "machine_written=%s user_verified=%s machine_verified=%s reloaded_user=%s "
            "reloaded_machine=%s",
            result.user_entries,
            result.machine_entries,
            result.machine_written,
            result.user_verified,
            result.machine_verified,
            result.reloaded_user_entries,
            result.reloaded_machine_entries,
        )
        if self._clear_app_entries is not None:
            self._clear_app_entries()
        if not result.user_verified or not result.machine_verified:
            show_message(
                parent=self,
                title="PATH saved with mismatch",
                message=(
                    "Windows PATH was written, but the immediate re-read did not match "
                    "what the app expected. Check wcommander.log for the expected and "
                    "reloaded values."
                ),
                level="warning",
            )
            return
        show_message(
            parent=self,
            title="PATH saved",
            message=(
                "Windows PATH was saved. "
                f"{'Machine PATH was also updated. ' if result.machine_written else ''}"
                "Restart already-open terminals and apps to pick it up."
            ),
        )
        self.accept()

    def _row_text(self, row: int) -> str:
        editor = self.table.cellWidget(row, 0)
        if isinstance(editor, QLineEdit):
            return editor.text()
        return ""

    def _set_row_text(self, row: int, value: str) -> None:
        editor = self.table.cellWidget(row, 0)
        if isinstance(editor, QLineEdit):
            editor.setText(value)

    def _row_source(self, row: int) -> str:
        source_label = self.table.cellWidget(row, 1)
        if isinstance(source_label, QLabel):
            source = source_label.property("pathSource")
            if source in {"machine", "user", "session"}:
                return str(source)
        return "user"

    def _set_row_source(self, row: int, source: str) -> None:
        source_label = self.table.cellWidget(row, 1)
        if isinstance(source_label, QLabel):
            source_label.setText(self._source_label(source))
            source_label.setProperty("pathSource", source)

    def _row_original(self, row: int) -> str:
        source_label = self.table.cellWidget(row, 1)
        if isinstance(source_label, QLabel):
            original = source_label.property("originalPathEntry")
            if isinstance(original, str):
                return original
        return ""

    def _set_row_original(self, row: int, original_entry: str) -> None:
        source_label = self.table.cellWidget(row, 1)
        if isinstance(source_label, QLabel):
            source_label.setProperty("originalPathEntry", original_entry)

    def _row_initial_display(self, row: int) -> str:
        source_label = self.table.cellWidget(row, 1)
        if isinstance(source_label, QLabel):
            original = source_label.property("initialDisplayPathEntry")
            if isinstance(original, str):
                return original
        return ""

    def _set_row_initial_display(self, row: int, value: str) -> None:
        source_label = self.table.cellWidget(row, 1)
        if isinstance(source_label, QLabel):
            source_label.setProperty("initialDisplayPathEntry", value)

    def _row_modified(self, row: int) -> bool:
        return self._row_text(row).strip() != self._row_initial_display(row).strip()

    def _select_editor_row(self, editor: QLineEdit) -> None:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0) is editor:
                self.table.selectRow(row)
                return

    def _infer_row_metadata(self) -> list[tuple[str, str]]:
        machine_entries = self._entry_key_map(self._snapshot.machine_entries)
        user_entries = self._entry_key_map(self._snapshot.user_entries)
        metadata: list[tuple[str, str]] = []
        for entry in self._snapshot.process_entries:
            key = path_entry_key(entry)
            if machine_entries.get(key):
                metadata.append(("machine", machine_entries[key].pop(0)))
            elif user_entries.get(key):
                metadata.append(("user", user_entries[key].pop(0)))
            else:
                metadata.append(("session", ""))
        return metadata

    def _entry_key_map(self, entries: list[str]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for entry in entries:
            result.setdefault(path_entry_key(entry), []).append(entry)
        return result

    def _source_label(self, source: str) -> str:
        if source == "machine":
            return "Machine"
        if source == "session":
            return "Session"
        return "User"
