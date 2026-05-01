from __future__ import annotations

import json

from multipane_commander.config.load import load_config, save_config
from multipane_commander.config.model import AiConfig, AppConfig


def test_ai_config_defaults_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    save_config(AppConfig())
    loaded = load_config()

    assert loaded.ai.enabled is True
    assert loaded.ai.model == ""


def test_ai_config_persists_custom_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    save_config(AppConfig(ai=AiConfig(enabled=False, model="claude-sonnet-4-6")))
    loaded = load_config()

    assert loaded.ai.enabled is False
    assert loaded.ai.model == "claude-sonnet-4-6"


def test_ai_config_falls_back_when_block_missing(tmp_path, monkeypatch) -> None:
    """A pre-AI config.json (no `ai` key) must still load — round-trips
    must not break for existing users."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_path = tmp_path / "MultiPaneCommander" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "theme": {"selected_theme_id": "windows-commander", "custom_themes": []},
                "terminal": {},
                "follow_active_pane_terminal": True,
                "show_terminal": True,
            }
        ),
        encoding="utf-8",
    )

    loaded = load_config()
    assert loaded.ai.enabled is True
    assert loaded.ai.model == ""


def test_ai_config_falls_back_on_malformed_block(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_path = tmp_path / "MultiPaneCommander" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "theme": {"selected_theme_id": "windows-commander", "custom_themes": []},
                "terminal": {},
                "ai": {"enabled": "false", "model": 42},  # both wrong-typed
                "follow_active_pane_terminal": True,
                "show_terminal": True,
            }
        ),
        encoding="utf-8",
    )

    loaded = load_config()
    assert loaded.ai.enabled is False  # _safe_bool coerces "false" -> False
    assert loaded.ai.model == ""  # non-string falls back to ""
