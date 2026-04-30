from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget


class FunctionKeyBar(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("functionKeyBar")
        self._extra_widget: QWidget | None = None
        self._extra_visible_width = 0
        self._required_widgets: list[QWidget] = []

    def add_required_widget(self, widget: QWidget) -> None:
        self._required_widgets.append(widget)

    def set_extra_widget(self, widget: QWidget) -> None:
        self._extra_widget = widget
        self._extra_visible_width = 0

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        hint = super().minimumSizeHint()
        action_width = self._action_only_width()
        if action_width > 0:
            hint.setWidth(action_width)
        return hint

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_extra_visibility()
        QTimer.singleShot(0, self._update_extra_visibility)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self._update_extra_visibility)

    def _update_extra_visibility(self) -> None:
        if self._extra_widget is None:
            return
        self._extra_visible_width = max(self._extra_visible_width, self._full_width())
        should_show = self.width() >= self._extra_visible_width
        if self._extra_widget.isVisible() == should_show:
            return
        self._extra_widget.setVisible(should_show)

    def _action_only_width(self) -> int:
        layout = self.layout()
        if layout is None:
            return 0
        margins = layout.contentsMargins()
        return (
            margins.left()
            + margins.right()
            + sum(widget.sizeHint().width() for widget in self._required_widgets)
        )

    def _full_width(self) -> int:
        action_width = self._action_only_width()
        if action_width <= 0 or self._extra_widget is None:
            return action_width
        return action_width + self._extra_widget.sizeHint().width()


class FunctionKeyButton(QPushButton):
    def __init__(self, key: str, label: str, handler: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName("functionKeyButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{key} {label}")
        self.setToolTip(f"{key} {label}")
        self.clicked.connect(handler)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(1)

        self.key_label = QLabel(key)
        self.key_label.setObjectName("functionKeyShortcut")
        self.key_label.setProperty("destructive", label.casefold() == "delete")
        self.key_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.action_label = QLabel(label)
        self.action_label.setObjectName("functionKeyText")
        self.action_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout.addWidget(self.key_label)
        layout.addWidget(self.action_label)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(self._content_width(), 34)

    def minimumSizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(self._content_width(), 34)

    def _content_width(self) -> int:
        self.ensurePolished()
        self.key_label.ensurePolished()
        self.action_label.ensurePolished()
        layout = self.layout()
        if layout is None:
            return 58
        margins = layout.contentsMargins()
        return (
            margins.left()
            + margins.right()
            + layout.spacing()
            + self.key_label.sizeHint().width()
            + self.action_label.sizeHint().width()
            + 4
        )


def _divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("functionKeyDivider")
    divider.setFixedWidth(1)
    divider.setFixedHeight(28)
    return divider


def build_function_key_bar(
    *,
    actions: list[tuple[str, str, Callable[[], None]]],
    extra_widget: QWidget | None = None,
) -> QWidget:

    frame = FunctionKeyBar()

    layout = QHBoxLayout(frame)
    layout.setContentsMargins(8, 7, 8, 7)
    layout.setSpacing(0)

    for index, (key, label, handler) in enumerate(actions):
        button = FunctionKeyButton(key, label, handler)
        layout.addWidget(button)
        frame.add_required_widget(button)
        if index < len(actions) - 1:
            divider = _divider()
            layout.addWidget(divider)
            frame.add_required_widget(divider)

    if extra_widget is not None:
        layout.addStretch(1)
        layout.addWidget(extra_widget)
        frame.set_extra_widget(extra_widget)

    return frame
