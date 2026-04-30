from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from multipane_commander.config.model import ThemeDefinition
from multipane_commander.ui.themes import slugify_theme_name


class ThemeEditorDialog(QDialog):
    preview_requested = Signal(object)

    def __init__(
        self,
        *,
        parent: QWidget | None,
        initial_theme: ThemeDefinition,
        available_themes: list[ThemeDefinition],
        selected_theme_id: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Theme")
        self.setModal(True)
        self.resize(580, 620)

        self._initial_theme = initial_theme
        self._initial_theme_id = selected_theme_id
        self._available_theme_map = {theme.id: theme for theme in available_themes}
        self._current_source_theme_id = selected_theme_id
        self._is_loading_theme = False
        self._fields: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Edit Theme")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "Adjust the core colors and save a theme that matches your preferred desktop feel."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)

        card = QFrame()
        card.setObjectName("dialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)
        card_layout.addLayout(form)

        self.theme_choice = QComboBox()
        for theme in available_themes:
            self.theme_choice.addItem(theme.display_name, theme.id)
        selected_index = self.theme_choice.findData(selected_theme_id)
        if selected_index >= 0:
            self.theme_choice.setCurrentIndex(selected_index)
        form.addRow("Theme", self.theme_choice)

        self.name_input = QLineEdit(initial_theme.display_name)
        form.addRow("Theme name", self.name_input)

        self.font_family_input = QFontComboBox()
        self.font_family_input.setCurrentFont(QFont(initial_theme.font_family))
        form.addRow("UI font", self.font_family_input)

        self.font_size_input = QSpinBox()
        self.font_size_input.setRange(8, 24)
        self.font_size_input.setValue(initial_theme.font_size)
        self.font_size_input.setSuffix(" pt")
        form.addRow("UI size", self.font_size_input)

        self._add_color_field(
            form,
            label="Window background",
            key="window_bg",
            value=initial_theme.window_bg,
        )
        self._add_color_field(
            form,
            label="Surface background",
            key="surface_bg",
            value=initial_theme.surface_bg,
        )
        self._add_color_field(
            form,
            label="Surface border",
            key="surface_border",
            value=initial_theme.surface_border,
        )
        self._add_color_field(
            form,
            label="Text",
            key="text_primary",
            value=initial_theme.text_primary,
        )
        self._add_color_field(
            form,
            label="Muted text",
            key="text_muted",
            value=initial_theme.text_muted,
        )
        self._add_color_field(
            form,
            label="Accent",
            key="accent",
            value=initial_theme.accent,
        )
        self._add_color_field(
            form,
            label="Accent text",
            key="accent_text",
            value=initial_theme.accent_text,
        )
        self._add_color_field(
            form,
            label="Button background",
            key="button_bg",
            value=initial_theme.button_bg,
        )
        self._add_color_field(
            form,
            label="Input background",
            key="input_bg",
            value=initial_theme.input_bg,
        )
        self._add_color_field(
            form,
            label="Warning accent",
            key="warning",
            value=initial_theme.warning,
        )
        self._add_color_field(
            form,
            label="Warning text",
            key="warning_text",
            value=initial_theme.warning_text,
        )

        preview_card = QFrame()
        preview_card.setObjectName("dialogCard")
        preview_card_layout = QVBoxLayout(preview_card)
        preview_card_layout.setContentsMargins(14, 14, 14, 14)
        preview_card_layout.setSpacing(6)

        preview_title = QLabel("Preview")
        preview_title.setObjectName("dialogSectionLabel")
        self.preview_sample = QLabel("Folders  Files  Preview  Terminal  Jobs")
        self.preview_sample.setObjectName("dialogPreviewSample")
        self.preview_details = QLabel("Aa 123 | The quick brown fox jumps over the lazy dog.")
        self.preview_details.setObjectName("dialogHint")

        preview_card_layout.addWidget(preview_title)
        preview_card_layout.addWidget(self.preview_sample)
        preview_card_layout.addWidget(self.preview_details)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        reset_button = QPushButton("Reset To Original")
        reset_button.setProperty("dialogRole", "secondary")
        reset_button.clicked.connect(self._reset_to_original)
        button_box.addButton(reset_button, QDialogButtonBox.ButtonRole.ResetRole)
        save_button = QPushButton("Save Theme")
        save_button.setProperty("dialogRole", "primary")
        save_button.setDefault(True)
        save_button.setAutoDefault(True)
        button_box.addButton(save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setProperty("dialogRole", "secondary")
            cancel_button.setAutoDefault(False)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        hint = QLabel("Press Enter to save the current theme.")
        hint.setObjectName("dialogHint")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(card, 1)
        layout.addWidget(preview_card)
        layout.addWidget(hint)
        layout.addWidget(button_box)

        self.name_input.selectAll()
        self.name_input.setFocus()
        self._wire_live_preview()
        self._refresh_preview_sample()

    def _add_color_field(self, form: QFormLayout, *, label: str, key: str, value: str) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        color_input = QLineEdit(value.upper())
        pick_button = QPushButton("Pick")
        pick_button.setProperty("dialogRole", "secondary")
        pick_button.clicked.connect(lambda: self._pick_color(color_input))

        row_layout.addWidget(color_input, 1)
        row_layout.addWidget(pick_button)
        self._fields[key] = color_input
        form.addRow(label, row)

    def _pick_color(self, target: QLineEdit) -> None:
        current = QColor(target.text().strip())
        color = QColorDialog.getColor(current, self, "Choose Color")
        if color.isValid():
            target.setText(color.name().upper())

    def _wire_live_preview(self) -> None:
        self.theme_choice.currentIndexChanged.connect(self._on_theme_choice_changed)
        self.name_input.textChanged.connect(self._on_preview_inputs_changed)
        self.font_family_input.currentFontChanged.connect(self._on_preview_inputs_changed)
        self.font_size_input.valueChanged.connect(self._on_preview_inputs_changed)
        for field in self._fields.values():
            field.textChanged.connect(self._on_preview_inputs_changed)

    def _on_theme_choice_changed(self) -> None:
        theme_id = self.theme_choice.currentData()
        if not isinstance(theme_id, str):
            return
        theme = self._available_theme_map.get(theme_id)
        if theme is None:
            return
        self._current_source_theme_id = theme_id
        self._load_theme(theme)

    def _on_preview_inputs_changed(self, *_args) -> None:
        if self._is_loading_theme:
            return
        self._refresh_preview_sample()
        self._emit_preview()

    def _load_theme(self, theme: ThemeDefinition) -> None:
        self._is_loading_theme = True
        try:
            self.name_input.setText(theme.display_name)
            self.font_family_input.setCurrentFont(QFont(theme.font_family))
            self.font_size_input.setValue(theme.font_size)
            self._fields["window_bg"].setText(theme.window_bg.upper())
            self._fields["surface_bg"].setText(theme.surface_bg.upper())
            self._fields["surface_border"].setText(theme.surface_border.upper())
            self._fields["text_primary"].setText(theme.text_primary.upper())
            self._fields["text_muted"].setText(theme.text_muted.upper())
            self._fields["accent"].setText(theme.accent.upper())
            self._fields["accent_text"].setText(theme.accent_text.upper())
            self._fields["button_bg"].setText(theme.button_bg.upper())
            self._fields["input_bg"].setText(theme.input_bg.upper())
            self._fields["warning"].setText(theme.warning.upper())
            self._fields["warning_text"].setText(theme.warning_text.upper())
        finally:
            self._is_loading_theme = False
        self._refresh_preview_sample()
        self._emit_preview()

    def _refresh_preview_sample(self) -> None:
        font = self.font_family_input.currentFont()
        font.setPointSize(self.font_size_input.value())
        self.preview_sample.setFont(font)
        self.preview_details.setFont(font)

    def _emit_preview(self) -> None:
        try:
            preview_theme = self.result_theme()
        except ValueError:
            return
        self.preview_requested.emit(preview_theme)

    def _reset_to_original(self) -> None:
        selected_index = self.theme_choice.findData(self._initial_theme_id)
        if selected_index >= 0:
            self.theme_choice.setCurrentIndex(selected_index)
        self._current_source_theme_id = self._initial_theme_id
        self._load_theme(self._initial_theme)

    def current_source_theme_id(self) -> str:
        return self._current_source_theme_id

    def selected_theme_id_for_save(self) -> str | None:
        current_theme = self.result_theme()
        source_theme = self._available_theme_map.get(self._current_source_theme_id)
        if source_theme is None:
            return None
        if current_theme == source_theme:
            return self._current_source_theme_id
        return None

    def result_theme(self) -> ThemeDefinition:
        display_name = self.name_input.text().strip() or "Custom Theme"
        return ThemeDefinition(
            id=slugify_theme_name(display_name),
            display_name=display_name,
            font_family=self.font_family_input.currentFont().family(),
            font_size=self.font_size_input.value(),
            window_bg=self._fields["window_bg"].text().strip(),
            surface_bg=self._fields["surface_bg"].text().strip(),
            surface_border=self._fields["surface_border"].text().strip(),
            text_primary=self._fields["text_primary"].text().strip(),
            text_muted=self._fields["text_muted"].text().strip(),
            accent=self._fields["accent"].text().strip(),
            accent_text=self._fields["accent_text"].text().strip(),
            button_bg=self._fields["button_bg"].text().strip(),
            input_bg=self._fields["input_bg"].text().strip(),
            warning=self._fields["warning"].text().strip(),
            warning_text=self._fields["warning_text"].text().strip(),
        )
