from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ThemeDefinition:
    id: str
    display_name: str
    font_family: str
    font_size: int
    window_bg: str
    surface_bg: str
    surface_border: str
    text_primary: str
    text_muted: str
    accent: str
    accent_text: str
    button_bg: str
    input_bg: str
    warning: str
    warning_text: str


@dataclass(slots=True)
class ThemeConfig:
    selected_theme_id: str = "windows-commander"
    custom_themes: list[ThemeDefinition] = field(default_factory=list)


@dataclass(slots=True)
class TerminalConfig:
    recent_commands: list[str] = field(default_factory=list)
    bookmarked_commands: list[str] = field(default_factory=list)
    history_panel_visible: bool = False
    experimental_pty: bool = False


@dataclass(slots=True)
class AiConfig:
    enabled: bool = True
    model: str = ""  # "" = use Claude Code / SDK default


@dataclass(slots=True)
class AppConfig:
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    follow_active_pane_terminal: bool = True
    show_terminal: bool = True
