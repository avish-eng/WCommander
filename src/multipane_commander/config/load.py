from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from multipane_commander.config.model import AppConfig, TerminalConfig, ThemeConfig, ThemeDefinition
from multipane_commander.platform import app_data_dir


def _config_file_path() -> Path:
    return app_data_dir() / "config.json"


def _theme_definition_from_payload(payload: object) -> ThemeDefinition | None:
    if not isinstance(payload, dict):
        return None
    try:
        return ThemeDefinition(
            id=str(payload["id"]),
            display_name=str(payload["display_name"]),
            font_family=str(payload.get("font_family", "Segoe UI")),
            font_size=int(payload.get("font_size", 10)),
            window_bg=str(payload["window_bg"]),
            surface_bg=str(payload["surface_bg"]),
            surface_border=str(payload["surface_border"]),
            text_primary=str(payload["text_primary"]),
            text_muted=str(payload["text_muted"]),
            accent=str(payload["accent"]),
            accent_text=str(payload["accent_text"]),
            button_bg=str(payload["button_bg"]),
            input_bg=str(payload["input_bg"]),
            warning=str(payload["warning"]),
            warning_text=str(payload["warning_text"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_config() -> AppConfig:
    config_path = _config_file_path()
    if not config_path.exists():
        return AppConfig()

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()
    if not isinstance(payload, dict):
        return AppConfig()

    theme_payload = payload.get("theme", {})
    legacy_theme_name = "windows-commander"
    if isinstance(theme_payload, dict):
        legacy_theme_name = str(
            theme_payload.get("selected_theme_id") or theme_payload.get("name") or legacy_theme_name
        )

    custom_themes: list[ThemeDefinition] = []
    if isinstance(theme_payload, dict):
        custom_themes_payload = theme_payload.get("custom_themes", [])
        if not isinstance(custom_themes_payload, list):
            custom_themes_payload = []
        for item in custom_themes_payload:
            theme = _theme_definition_from_payload(item)
            if theme is not None:
                custom_themes.append(theme)

    terminal_payload = payload.get("terminal", {})
    if not isinstance(terminal_payload, dict):
        terminal_payload = {}

    return AppConfig(
        theme=ThemeConfig(
            selected_theme_id=legacy_theme_name,
            custom_themes=custom_themes,
        ),
        terminal=TerminalConfig(
            recent_commands=_string_list(terminal_payload.get("recent_commands", [])),
            bookmarked_commands=_string_list(terminal_payload.get("bookmarked_commands", [])),
            history_panel_visible=_safe_bool(terminal_payload.get("history_panel_visible"), False),
            experimental_pty=_safe_bool(terminal_payload.get("experimental_pty"), False),
        ),
        follow_active_pane_terminal=_safe_bool(
            payload.get("follow_active_pane_terminal"),
            True,
        ),
        show_terminal=_safe_bool(payload.get("show_terminal"), True),
    )


def _safe_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if value is None:
        return default
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def save_config(config: AppConfig) -> None:
    config_path = _config_file_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "theme": {
            "selected_theme_id": config.theme.selected_theme_id,
            "custom_themes": [asdict(theme) for theme in config.theme.custom_themes],
        },
        "terminal": {
            "recent_commands": config.terminal.recent_commands,
            "bookmarked_commands": config.terminal.bookmarked_commands,
            "history_panel_visible": config.terminal.history_panel_visible,
            "experimental_pty": config.terminal.experimental_pty,
        },
        "follow_active_pane_terminal": config.follow_active_pane_terminal,
        "show_terminal": config.show_terminal,
    }
    config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
