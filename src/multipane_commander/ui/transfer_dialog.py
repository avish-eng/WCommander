from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


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
        browse_hint = QLabel("Paste/edit the destination path directly.")
        browse_hint.setObjectName("dialogHint")
        browse_hint.setWordWrap(True)

        destination_row = QHBoxLayout()
        destination_row.addWidget(self.destination_edit, 1)
        normalize_button = QPushButton("Use current")
        normalize_button.setProperty("dialogRole", "secondary")
        normalize_button.clicked.connect(
            lambda: self.destination_edit.setText(str(default_destination))
        )
        destination_row.addWidget(normalize_button)

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

    def destination_directory(self) -> Path:
        return Path(self.destination_edit.text()).expanduser()

    def conflict_policy(self) -> str:
        return str(self.conflict_policy_combo.currentData())
