from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TextEntryDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget | None,
        title: str,
        subtitle: str,
        field_label: str,
        initial_value: str,
        accept_label: str,
        placeholder: str = "",
        hint: str = "",
        select_all: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(520, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setWordWrap(True)

        card = QFrame()
        card.setObjectName("dialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(8)

        field_title = QLabel(field_label)
        field_title.setObjectName("dialogSectionLabel")

        self.input = QLineEdit(initial_value)
        if placeholder:
            self.input.setPlaceholderText(placeholder)

        card_layout.addWidget(field_title)
        card_layout.addWidget(self.input)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("dialogHint")
            hint_label.setWordWrap(True)
            card_layout.addWidget(hint_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
        )
        accept_button = QPushButton(accept_label)
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

        enter_hint = QLabel(f"Press Enter to {accept_label.lower()}.")
        enter_hint.setObjectName("dialogHint")

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addWidget(card)
        layout.addWidget(enter_hint)
        layout.addWidget(buttons)

        if select_all:
            self.input.selectAll()
        self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def value(self) -> str:
        return self.input.text()


def ask_confirmation(
    *,
    parent: QWidget | None,
    title: str,
    message: str,
    accept_label: str,
    cancel_label: str = "Cancel",
    is_destructive: bool = False,
) -> bool:
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setIcon(QMessageBox.Icon.Warning if is_destructive else QMessageBox.Icon.Question)
    dialog.setText(title)
    dialog.setInformativeText(message)
    dialog.setStandardButtons(QMessageBox.StandardButton.NoButton)

    accept_button = dialog.addButton(accept_label, QMessageBox.ButtonRole.AcceptRole)
    cancel_button = dialog.addButton(cancel_label, QMessageBox.ButtonRole.RejectRole)
    accept_button.setProperty("dialogRole", "primary")
    cancel_button.setProperty("dialogRole", "secondary")
    accept_button.setDefault(True)
    accept_button.setAutoDefault(True)
    cancel_button.setAutoDefault(False)
    dialog.setEscapeButton(cancel_button)
    dialog.setDefaultButton(accept_button)
    dialog.exec()
    return dialog.clickedButton() is accept_button


def show_message(
    *,
    parent: QWidget | None,
    title: str,
    message: str,
    details: str = "",
    level: str = "info",
    accept_label: str = "OK",
) -> None:
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    icon = QMessageBox.Icon.Information
    if level == "error":
        icon = QMessageBox.Icon.Critical
    elif level == "warning":
        icon = QMessageBox.Icon.Warning
    dialog.setIcon(icon)
    dialog.setText(title)
    dialog.setInformativeText(message)
    if details:
        dialog.setDetailedText(details)
    dialog.setStandardButtons(QMessageBox.StandardButton.NoButton)
    accept_button = dialog.addButton(accept_label, QMessageBox.ButtonRole.AcceptRole)
    accept_button.setProperty("dialogRole", "primary")
    accept_button.setDefault(True)
    accept_button.setAutoDefault(True)
    dialog.setDefaultButton(accept_button)
    dialog.exec()
