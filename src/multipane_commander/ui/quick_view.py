from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class QuickViewWidget(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("quickView")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._size_presets = {
            "Compact": {"image_scale": 0.72, "text_points": 9},
            "Comfortable": {"image_scale": 1.0, "text_points": 10},
            "Large": {"image_scale": 1.28, "text_points": 12},
        }

        self.title_label = QLabel("Quick View")
        self.title_label.setObjectName("quickViewTitle")
        self.title_meta_label = QLabel("")
        self.title_meta_label.setObjectName("quickViewMeta")
        self.meta_label = QLabel("Select a file to preview.")
        self.meta_label.setObjectName("quickViewMeta")
        self.meta_label.setWordWrap(True)
        self.size_picker = QComboBox()
        self.size_picker.setObjectName("quickViewSizePicker")
        self.size_picker.addItems(list(self._size_presets))
        self.size_picker.setCurrentText("Comfortable")
        self.size_picker.currentTextChanged.connect(self._apply_size_preset)

        self.stack = QStackedWidget()

        self.empty_label = QLabel("No preview available.")
        self.empty_label.setObjectName("quickViewEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text_preview = QPlainTextEdit()
        self.text_preview.setObjectName("quickViewText")
        self.text_preview.setReadOnly(True)

        self.image_label = QLabel()
        self.image_label.setObjectName("quickViewImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setWidget(self.image_label)

        self.stack.addWidget(self.empty_label)
        self.stack.addWidget(self.text_preview)
        self.stack.addWidget(self.image_scroll)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(self.title_label)
        header_row.addWidget(self.title_meta_label)
        header_row.addStretch(1)
        header_row.addWidget(self.size_picker)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(header_row)
        layout.addWidget(self.meta_label)
        layout.addWidget(self.stack, 1)

        self._current_pixmap: QPixmap | None = None
        self._apply_size_preset(self.size_picker.currentText())

    def current_size_preset(self) -> str:
        return self.size_picker.currentText()

    def set_size_preset(self, preset_name: str) -> None:
        if preset_name not in self._size_presets:
            preset_name = "Comfortable"
        self.size_picker.setCurrentText(preset_name)

    def show_path(self, path: Path | None) -> None:
        if path is None:
            self.title_label.setText("Quick View")
            self.title_meta_label.clear()
            self.meta_label.setText("Select a file to preview.")
            self.meta_label.setVisible(True)
            self.stack.setCurrentWidget(self.empty_label)
            self.text_preview.clear()
            self.image_label.clear()
            self._current_pixmap = None
            return

        self.title_label.setText(path.name or str(path))
        self.title_meta_label.clear()
        self.meta_label.setVisible(True)
        if path.is_dir():
            self.meta_label.setText("Folder selected")
            self.stack.setCurrentWidget(self.empty_label)
            self.empty_label.setText("Folder selected.\nOpen it to browse its contents.")
            return

        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._current_pixmap = pixmap
                self.title_meta_label.setText(f"{pixmap.width()} x {pixmap.height()} px")
                self.meta_label.clear()
                self.meta_label.setVisible(False)
                self._update_scaled_pixmap()
                self.stack.setCurrentWidget(self.image_scroll)
                return

        try:
            file_size = path.stat().st_size
            with path.open("rb") as handle:
                raw = handle.read(80_000)
        except OSError as exc:
            self.meta_label.setText(f"{path}\n{exc}")
            self.stack.setCurrentWidget(self.empty_label)
            self.empty_label.setText("Unable to preview this item.")
            return

        if b"\x00" not in raw:
            text = raw[:80_000].decode("utf-8", errors="replace")
            self.meta_label.setText("Text file")
            self.text_preview.setPlainText(text)
            self.stack.setCurrentWidget(self.text_preview)
            return

        self.meta_label.setText(f"Binary file • {file_size:,} bytes")
        self.stack.setCurrentWidget(self.empty_label)
        self.empty_label.setText("Binary preview is not available yet.")

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self._update_scaled_pixmap()
        super().resizeEvent(event)

    def _update_scaled_pixmap(self) -> None:
        if self._current_pixmap is None:
            return
        preset = self._size_presets[self.size_picker.currentText()]
        viewport_size = self.image_scroll.viewport().size()
        target_size = viewport_size.expandedTo(viewport_size)
        target_size.setWidth(max(1, int(viewport_size.width() * preset["image_scale"])))
        target_size.setHeight(max(1, int(viewport_size.height() * preset["image_scale"])))
        scaled = self._current_pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _apply_size_preset(self, preset_name: str) -> None:
        preset = self._size_presets[preset_name]
        font = QFont(self.text_preview.font())
        font.setPointSize(preset["text_points"])
        self.text_preview.setFont(font)
        self._update_scaled_pixmap()
