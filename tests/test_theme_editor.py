from __future__ import annotations

import json
import os
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from multipane_commander.config.model import AppConfig, ThemeConfig
from multipane_commander.services.theme_backups import backup_theme_definition
from multipane_commander.ui.main_window import MainWindow
from multipane_commander.ui.theme_editor import ThemeEditorDialog
from multipane_commander.ui.themes import build_palette, build_stylesheet, builtin_themes


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def _custom_theme():
    return replace(
        builtin_themes()[0],
        id="custom-test-theme",
        display_name="Custom Test Theme",
    )


def test_reference_inspired_builtin_themes_are_available_and_valid() -> None:
    themes = {theme.id: theme for theme in builtin_themes()}

    assert {
        "graphite-board",
        "editorial-light",
        "frosted-planner",
    } <= themes.keys()
    for theme_id in ("graphite-board", "editorial-light", "frosted-planner"):
        palette = build_palette(themes[theme_id])
        stylesheet = build_stylesheet(themes[theme_id])
        assert palette.text_primary.startswith("#")
        assert theme_id.split("-")[0].title() in themes[theme_id].display_name
        assert stylesheet


def test_theme_editor_can_make_selected_theme_default() -> None:
    _qapp()
    builtins = builtin_themes()
    custom = _custom_theme()
    dialog = ThemeEditorDialog(
        parent=None,
        initial_theme=custom,
        available_themes=[*builtins, custom],
        selected_theme_id=custom.id,
    )
    requested: list[str] = []
    dialog.default_theme_requested.connect(requested.append)

    dialog.theme_choice.setCurrentIndex(dialog.theme_choice.findData(builtins[0].id))
    assert dialog.make_default_button.isEnabled()
    dialog.make_default_button.click()

    assert requested == [builtins[0].id]
    assert not dialog.make_default_button.isEnabled()
    assert dialog.make_default_button.text() == "Default"


def test_theme_editor_deletes_custom_theme(monkeypatch) -> None:
    _qapp()
    builtins = builtin_themes()
    custom = _custom_theme()
    dialog = ThemeEditorDialog(
        parent=None,
        initial_theme=custom,
        available_themes=[*builtins, custom],
        selected_theme_id=custom.id,
    )
    monkeypatch.setattr(
        "multipane_commander.ui.theme_editor.ask_confirmation",
        lambda **_kwargs: True,
    )
    backed_up: list[object] = []
    monkeypatch.setattr(
        "multipane_commander.ui.theme_editor.backup_theme_definition",
        backed_up.append,
    )
    deleted: list[str] = []
    dialog.delete_theme_requested.connect(deleted.append)

    assert dialog.delete_theme_button.isEnabled()
    dialog.delete_theme_button.click()

    assert deleted == [custom.id]
    assert backed_up == [custom]
    assert dialog.theme_choice.findData(custom.id) == -1
    assert dialog.theme_choice.currentData() == builtins[0].id
    assert dialog.delete_theme_button.isEnabled()


def test_theme_editor_can_delete_builtin_theme(monkeypatch) -> None:
    _qapp()
    builtins = builtin_themes()
    dialog = ThemeEditorDialog(
        parent=None,
        initial_theme=builtins[0],
        available_themes=builtins,
        selected_theme_id=builtins[0].id,
    )
    monkeypatch.setattr(
        "multipane_commander.ui.theme_editor.ask_confirmation",
        lambda **_kwargs: True,
    )
    backed_up: list[object] = []
    monkeypatch.setattr(
        "multipane_commander.ui.theme_editor.backup_theme_definition",
        backed_up.append,
    )
    deleted: list[str] = []
    dialog.delete_theme_requested.connect(deleted.append)

    dialog.delete_theme_button.click()

    assert deleted == [builtins[0].id]
    assert backed_up == [builtins[0]]
    assert dialog.theme_choice.findData(builtins[0].id) == -1
    assert dialog.theme_choice.currentData() == builtins[1].id


def test_theme_editor_keeps_last_remaining_theme() -> None:
    _qapp()
    theme = builtin_themes()[0]
    dialog = ThemeEditorDialog(
        parent=None,
        initial_theme=theme,
        available_themes=[theme],
        selected_theme_id=theme.id,
    )

    assert not dialog.delete_theme_button.isEnabled()
    assert dialog.delete_theme_button.toolTip() == "At least one theme must remain"


def test_theme_editor_keeps_theme_when_backup_fails(monkeypatch) -> None:
    _qapp()
    builtins = builtin_themes()
    custom = _custom_theme()
    dialog = ThemeEditorDialog(
        parent=None,
        initial_theme=custom,
        available_themes=[*builtins, custom],
        selected_theme_id=custom.id,
    )
    monkeypatch.setattr(
        "multipane_commander.ui.theme_editor.ask_confirmation",
        lambda **_kwargs: True,
    )

    def fail_backup(_theme) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(
        "multipane_commander.ui.theme_editor.backup_theme_definition",
        fail_backup,
    )
    errors: list[dict] = []
    monkeypatch.setattr(
        "multipane_commander.ui.theme_editor.show_message",
        lambda **kwargs: errors.append(kwargs),
    )
    deleted: list[str] = []
    dialog.delete_theme_requested.connect(deleted.append)

    dialog.delete_theme_button.click()

    assert deleted == []
    assert dialog.theme_choice.findData(custom.id) >= 0
    assert errors and errors[0]["title"] == "Theme backup failed"


def test_main_window_persists_new_default_theme(monkeypatch) -> None:
    builtins = builtin_themes()
    custom = _custom_theme()
    config = AppConfig(
        theme=ThemeConfig(selected_theme_id=custom.id, custom_themes=[custom])
    )
    applied: list[bool] = []
    persisted: list[object] = []
    window = SimpleNamespace(
        context=SimpleNamespace(config=config),
        _apply_selected_theme=lambda: applied.append(True),
    )
    monkeypatch.setattr(
        "multipane_commander.ui.main_window.persist_app_context",
        persisted.append,
    )

    MainWindow._set_default_theme(window, builtins[0].id)

    assert config.theme.selected_theme_id == builtins[0].id
    assert applied == [True]
    assert persisted == [window.context]


def test_main_window_deleting_default_custom_theme_uses_builtin_fallback(
    monkeypatch,
) -> None:
    custom = _custom_theme()
    config = AppConfig(
        theme=ThemeConfig(selected_theme_id=custom.id, custom_themes=[custom])
    )
    applied: list[bool] = []
    persisted: list[object] = []
    window = SimpleNamespace(
        context=SimpleNamespace(config=config),
        _apply_selected_theme=lambda: applied.append(True),
    )
    monkeypatch.setattr(
        "multipane_commander.ui.main_window.persist_app_context",
        persisted.append,
    )

    MainWindow._delete_theme(window, custom.id)

    assert config.theme.custom_themes == []
    assert config.theme.selected_theme_id == builtin_themes()[0].id
    assert applied == [True]
    assert persisted == [window.context]


def test_main_window_deletes_builtin_theme_and_selects_fallback(monkeypatch) -> None:
    builtins = builtin_themes()
    config = AppConfig(theme=ThemeConfig(selected_theme_id=builtins[0].id))
    applied: list[bool] = []
    persisted: list[object] = []
    window = SimpleNamespace(
        context=SimpleNamespace(config=config),
        _apply_selected_theme=lambda: applied.append(True),
    )
    monkeypatch.setattr(
        "multipane_commander.ui.main_window.persist_app_context",
        persisted.append,
    )

    MainWindow._delete_theme(window, builtins[0].id)

    assert config.theme.deleted_builtin_theme_ids == [builtins[0].id]
    assert config.theme.selected_theme_id == builtins[1].id
    assert applied == [True]
    assert persisted == [window.context]


def test_deleted_theme_is_written_to_backup_themes_folder(tmp_path) -> None:
    theme = _custom_theme()

    backup_path = backup_theme_definition(theme, backup_dir=tmp_path / "backup themes")

    assert backup_path == tmp_path / "backup themes" / f"{theme.id}.json"
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    assert payload["id"] == theme.id
    assert payload["display_name"] == theme.display_name
    assert payload["window_bg"] == theme.window_bg
