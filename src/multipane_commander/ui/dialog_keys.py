from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QAbstractButton, QComboBox, QDialog, QWidget


_BLOCKING_MODIFIERS = (
    Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
    | Qt.KeyboardModifier.ShiftModifier
)


class _DialogKeyFilter(QObject):
    def __init__(
        self,
        dialog: QDialog,
        *,
        accept: Callable[[], None],
        reject: Callable[[], None],
        ignore_accept_for: Callable[[QWidget], bool] | None,
    ) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._accept = accept
        self._reject = reject
        self._ignore_accept_for = ignore_accept_for
        self._app = QApplication.instance()
        if self._app is not None:
            self._app.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() != QEvent.Type.KeyPress:
            return False
        if not self._dialog.isVisible():
            return False

        focus_widget = QApplication.focusWidget()
        if not self._belongs_to_dialog(focus_widget):
            return False
        if self._combo_popup_is_open():
            return False

        key = event.key()
        if event.modifiers() & _BLOCKING_MODIFIERS:
            return False

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._ignore_accept_for is not None and self._ignore_accept_for(focus_widget):
                return False
            self._activate_default(focus_widget)
            event.accept()
            return True

        if key == Qt.Key.Key_Escape:
            self._reject()
            event.accept()
            return True

        return False

    def _belongs_to_dialog(self, widget: QWidget | None) -> bool:
        if widget is None:
            return False
        return widget is self._dialog or self._dialog.isAncestorOf(widget)

    def _activate_default(self, focus_widget: QWidget | None) -> None:
        if isinstance(focus_widget, QAbstractButton) and focus_widget.isEnabled():
            focus_widget.click()
            return
        self._accept()

    def _combo_popup_is_open(self) -> bool:
        for combo in self._dialog.findChildren(QComboBox):
            if combo.view().isVisible():
                return True
        return False


def install_dialog_key_bindings(
    dialog: QDialog,
    *,
    accept: Callable[[], None] | None = None,
    reject: Callable[[], None] | None = None,
    ignore_accept_for: Callable[[QWidget], bool] | None = None,
) -> None:
    key_filter = _DialogKeyFilter(
        dialog,
        accept=accept or dialog.accept,
        reject=reject or dialog.reject,
        ignore_accept_for=ignore_accept_for,
    )
    filters = getattr(dialog, "_dialog_key_filters", [])
    filters.append(key_filter)
    setattr(dialog, "_dialog_key_filters", filters)
