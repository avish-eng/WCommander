from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from multipane_commander.ui.dialog_keys import install_dialog_key_bindings


class TransferDialog(QDialog):
    def __init__(
        self,
        *,
        operation: str,
        source_paths: list[Path],
        default_destination: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{operation.title()} Items")
        self.resize(620, 420)
        self.setModal(True)

        self.operation = operation
        self.destination_edit = QLineEdit(str(default_destination))
        self._default_destination = default_destination
        self._validation = QLabel()
        self._validation.setWordWrap(True)
        self._validation.setObjectName("dialogValidation")
        self._validation.hide()
        self.conflict_policy_combo = QComboBox()
        self.conflict_policy_combo.addItem("Ask for each conflict", "ask")
        self.conflict_policy_combo.addItem("Overwrite existing", "overwrite")
        self.conflict_policy_combo.addItem("Skip existing", "skip")
        self.conflict_policy_combo.addItem("Keep both (auto-rename)", "keep_both")
        self.preview_list = QListWidget()

        title = QLabel(f"{operation.title()} {len(source_paths)} item(s)")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "Review the destination before starting the operation."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)

        destination_label = QLabel("Destination folder")
        destination_label.setObjectName("dialogSectionLabel")
        conflict_label = QLabel("If a file already exists")
        conflict_label.setObjectName("dialogSectionLabel")
        browse_hint = QLabel("Relative paths start in the target pane's folder.")
        browse_hint.setObjectName("dialogHint")
        browse_hint.setWordWrap(True)

        destination_row = QHBoxLayout()
        destination_row.addWidget(self.destination_edit, 1)
        normalize_button = QPushButton("Use target pane")
        normalize_button.setToolTip(str(default_destination))
        normalize_button.setProperty("dialogRole", "secondary")
        normalize_button.clicked.connect(
            lambda: self.destination_edit.setText(str(default_destination))
        )
        destination_row.addWidget(normalize_button)
        browse_button = QPushButton("Browse…")
        browse_button.setAutoDefault(False)
        browse_button.clicked.connect(self._browse_destination)
        destination_row.addWidget(browse_button)

        for path in source_paths:
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            self.preview_list.addItem(item)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        accept_button = QPushButton(f"Start {operation.title()}")
        accept_button.setProperty("dialogRole", "primary")
        accept_button.setDefault(True)
        accept_button.setAutoDefault(True)
        buttons.addButton(accept_button, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setProperty("dialogRole", "secondary")
            cancel_button.setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        destination_card = QFrame()
        destination_card.setObjectName("dialogCard")
        destination_card_layout = QVBoxLayout(destination_card)
        destination_card_layout.setContentsMargins(14, 14, 14, 14)
        destination_card_layout.setSpacing(8)
        destination_card_layout.addWidget(destination_label)
        destination_card_layout.addLayout(destination_row)
        destination_card_layout.addWidget(browse_hint)
        destination_card_layout.addWidget(self._validation)

        conflict_card = QFrame()
        conflict_card.setObjectName("dialogCard")
        conflict_card_layout = QVBoxLayout(conflict_card)
        conflict_card_layout.setContentsMargins(14, 14, 14, 14)
        conflict_card_layout.setSpacing(8)
        conflict_card_layout.addWidget(conflict_label)
        conflict_card_layout.addWidget(self.conflict_policy_combo)

        items_label = QLabel("Items")
        items_label.setObjectName("dialogSectionLabel")

        items_card = QFrame()
        items_card.setObjectName("dialogCard")
        items_card_layout = QVBoxLayout(items_card)
        items_card_layout.setContentsMargins(14, 14, 14, 14)
        items_card_layout.setSpacing(8)
        items_card_layout.addWidget(items_label)
        items_card_layout.addWidget(self.preview_list, 1)

        enter_hint = QLabel(f"Press Enter to start {operation.lower()}.")
        enter_hint.setObjectName("dialogHint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(destination_card)
        layout.addWidget(conflict_card)
        layout.addWidget(items_card, 1)
        layout.addWidget(enter_hint)
        layout.addWidget(buttons)

        self.destination_edit.setFocus()
        self.destination_edit.selectAll()
        install_dialog_key_bindings(self, accept=accept_button.click)

    def destination_directory(self) -> Path:
        value = self.destination_edit.text().strip()
        if not value:
            raise ValueError("Choose a destination folder.")
        destination = Path(value).expanduser()
        if not destination.is_absolute():
            destination = self._default_destination / destination
        return destination.resolve()

    def accept(self) -> None:
        try:
            destination = self.destination_directory()
            if not destination.is_dir():
                raise ValueError("The destination folder does not exist.")
        except (ValueError, OSError, RuntimeError) as error:
            self._validation.setText(str(error))
            self._validation.show()
            self.destination_edit.setFocus()
            return
        self.destination_edit.setText(str(destination))
        self._validation.hide()
        super().accept()

    def conflict_policy(self) -> str:
        return str(self.conflict_policy_combo.currentData())

    def _browse_destination(self) -> None:
        try:
            initial = str(self.destination_directory())
        except (ValueError, OSError, RuntimeError):
            initial = str(self._default_destination)
        selected = QFileDialog.getExistingDirectory(self, "Destination folder", initial)
        if selected:
            self.destination_edit.setText(selected)
            self._validation.hide()
