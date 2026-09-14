from __future__ import annotations

from PySide6.QtCore import Property, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QListWidget, QStyledItemDelegate, QStyleOptionViewItem

PINNED_COMMAND_ROLE = Qt.ItemDataRole.UserRole
MAX_HISTORY_ITEMS = 100


class CommandHistoryList(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self._pinned_text_color = QColor("#D8A144")

    def _get_pinned_text_color(self) -> QColor:
        return self._pinned_text_color

    def _set_pinned_text_color(self, color: QColor) -> None:
        self._pinned_text_color = QColor(color)
        self.viewport().update()

    pinnedTextColor = Property(
        QColor,
        _get_pinned_text_color,
        _set_pinned_text_color,
    )


class CommandHistoryDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        pinned = bool(index.data(PINNED_COMMAND_ROLE))
        paint_option = QStyleOptionViewItem(option)
        if pinned:
            accent = option.palette.highlight().color()
            tint = QColor(accent)
            tint.setAlpha(24)
            painter.fillRect(option.rect, tint)
            history_list = self.parent()
            if isinstance(history_list, CommandHistoryList):
                pinned_text = history_list._get_pinned_text_color()
                paint_option.palette.setColor(QPalette.ColorRole.Text, pinned_text)
                paint_option.palette.setColor(
                    QPalette.ColorRole.HighlightedText,
                    pinned_text,
                )

        super().paint(painter, paint_option, index)

        if pinned:
            painter.fillRect(option.rect.x(), option.rect.y(), 2, option.rect.height(), accent)


def trim_history(
    recent: list[str],
    pinned: list[str],
    command_key,
    limit: int = MAX_HISTORY_ITEMS,
) -> list[str]:
    pinned_keys = {command_key(command) for command in pinned}
    budget = max(0, limit - len(pinned_keys))
    trimmed: list[str] = []
    visible = 0
    for command in recent:
        if command_key(command) in pinned_keys:
            trimmed.append(command)
            continue
        if visible >= budget:
            break
        trimmed.append(command)
        visible += 1
    return trimmed
