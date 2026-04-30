import json

from multipane_commander.config.load import load_config, save_config
from multipane_commander.config.model import AppConfig, TerminalConfig, ThemeConfig, ThemeDefinition


def test_config_store_persists_theme_selection_and_custom_themes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))

    config = AppConfig(
        theme=ThemeConfig(
            selected_theme_id="ocean-night",
            custom_themes=[
                ThemeDefinition(
                    id="ocean-night",
                    display_name="Ocean Night",
                    font_family="Cascadia Mono",
                    font_size=11,
                    window_bg="#081522",
                    surface_bg="#0D2033",
                    surface_border="#274562",
                    text_primary="#EAF4FF",
                    text_muted="#92A9C7",
                    accent="#53D1FF",
                    accent_text="#F7FBFF",
                    button_bg="#14314C",
                    input_bg="#0B1B2B",
                    warning="#F2B450",
                    warning_text="#2A1A00",
                )
            ],
        ),
        terminal=TerminalConfig(
            recent_commands=["pytest -q", "git status"],
            bookmarked_commands=["python run_app.py"],
            history_panel_visible=True,
            experimental_pty=True,
        ),
        follow_active_pane_terminal=False,
        show_terminal=False,
    )

    save_config(config)
    loaded = load_config()

    assert loaded.theme.selected_theme_id == "ocean-night"
    assert len(loaded.theme.custom_themes) == 1
    assert loaded.theme.custom_themes[0].display_name == "Ocean Night"
    assert loaded.theme.custom_themes[0].font_family == "Cascadia Mono"
    assert loaded.theme.custom_themes[0].font_size == 11
    assert loaded.terminal.recent_commands == ["pytest -q", "git status"]
    assert loaded.terminal.bookmarked_commands == ["python run_app.py"]
    assert loaded.terminal.history_panel_visible is True
    assert loaded.terminal.experimental_pty is True
    assert loaded.follow_active_pane_terminal is False
    assert loaded.show_terminal is False


def test_config_store_handles_malformed_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_path = tmp_path / "MultiPaneCommander" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "theme": {
                    "selected_theme_id": "windows-commander",
                    "custom_themes": [
                        {
                            "id": "broken",
                            "display_name": "Broken",
                            "font_size": "large",
                        }
                    ],
                },
                "terminal": {
                    "experimental_pty": "false",
                },
                "follow_active_pane_terminal": "false",
                "show_terminal": None,
            }
        ),
        encoding="utf-8",
    )

    loaded = load_config()

    assert loaded.theme.selected_theme_id == "windows-commander"
    assert loaded.theme.custom_themes == []
    assert loaded.terminal.experimental_pty is False
    assert loaded.follow_active_pane_terminal is False
    assert loaded.show_terminal is True
