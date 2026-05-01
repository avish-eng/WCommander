from __future__ import annotations

from dataclasses import dataclass

from multipane_commander.config.model import ThemeDefinition


def _normalize_hex(value: str) -> str:
    color = value.strip()
    if not color.startswith("#"):
        color = f"#{color}"
    color = color.upper()
    if len(color) == 4:
        color = "#" + "".join(character * 2 for character in color[1:])
    if len(color) != 7:
        raise ValueError(f"Invalid color: {value}")
    int(color[1:], 16)
    return color


def _rgb(color: str) -> tuple[int, int, int]:
    normalized = _normalize_hex(color)
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _mix(color_a: str, color_b: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    a = _rgb(color_a)
    b = _rgb(color_b)
    return _hex(
        tuple(
            round(a[index] + (b[index] - a[index]) * amount)
            for index in range(3)
        )
    )


def _lighten(color: str, amount: float) -> str:
    return _mix(color, "#FFFFFF", amount)


def _darken(color: str, amount: float) -> str:
    return _mix(color, "#000000", amount)


def _rgba(color: str, alpha: float) -> str:
    red, green, blue = _rgb(color)
    clamped = max(0.0, min(1.0, alpha))
    return f"rgba({red}, {green}, {blue}, {clamped:.2f})"


def slugify_theme_name(name: str) -> str:
    cleaned: list[str] = []
    previous_dash = False
    for character in name.strip().lower():
        if character.isalnum():
            cleaned.append(character)
            previous_dash = False
            continue
        if not previous_dash:
            cleaned.append("-")
            previous_dash = True
    slug = "".join(cleaned).strip("-")
    return slug or "custom-theme"


def builtin_themes() -> list[ThemeDefinition]:
    return [
        ThemeDefinition(
            id="windows-commander",
            display_name="Current (Windows Commander)",
            font_family="Segoe UI",
            font_size=10,
            window_bg="#08111D",
            surface_bg="#0B1324",
            surface_border="#263754",
            text_primary="#E7EDF8",
            text_muted="#8CA0C3",
            accent="#4FD1FF",
            accent_text="#F7FBFF",
            button_bg="#16253F",
            input_bg="#0B1324",
            warning="#D8A144",
            warning_text="#FFF1DE",
        ),
        ThemeDefinition(
            id="mac-graphite",
            display_name="Mac",
            font_family="SF Pro Text",
            font_size=13,
            window_bg="#161719",
            surface_bg="#202226",
            surface_border="#383C43",
            text_primary="#F4F6F8",
            text_muted="#A3AAB5",
            accent="#69A7FF",
            accent_text="#F6FAFF",
            button_bg="#2A2D33",
            input_bg="#1B1D22",
            warning="#F0B95C",
            warning_text="#2F2410",
        ),
        ThemeDefinition(
            id="windows-modern",
            display_name="Windows",
            font_family="Segoe UI",
            font_size=10,
            window_bg="#0E1525",
            surface_bg="#152033",
            surface_border="#2B3B55",
            text_primary="#F5F9FF",
            text_muted="#A6B5CB",
            accent="#4CC2FF",
            accent_text="#F7FBFF",
            button_bg="#1B2A42",
            input_bg="#111B2D",
            warning="#F1B24A",
            warning_text="#2F1D06",
        ),
        ThemeDefinition(
            id="midnight-neon",
            display_name="Midnight Neon",
            font_family="Inter",
            font_size=10,
            window_bg="#120B25",
            surface_bg="#1A1232",
            surface_border="#3F2E66",
            text_primary="#F5F1FF",
            text_muted="#B2A7D8",
            accent="#4CF4E6",
            accent_text="#08201D",
            button_bg="#271B47",
            input_bg="#150F2A",
            warning="#FFB347",
            warning_text="#2E1800",
        ),
        ThemeDefinition(
            id="solarized-dark",
            display_name="Solarized Dark",
            font_family="Segoe UI",
            font_size=10,
            window_bg="#002B36",
            surface_bg="#073642",
            surface_border="#275361",
            text_primary="#EEE8D5",
            text_muted="#93A1A1",
            accent="#2AA198",
            accent_text="#F4FFF9",
            button_bg="#0C4A5A",
            input_bg="#06303A",
            warning="#CB8B16",
            warning_text="#FFF6DE",
        ),
        ThemeDefinition(
            id="forest-night",
            display_name="Forest Night",
            font_family="Segoe UI",
            font_size=10,
            window_bg="#0B1712",
            surface_bg="#12231C",
            surface_border="#2C4A3F",
            text_primary="#EDF7F1",
            text_muted="#96AE9F",
            accent="#6BE28A",
            accent_text="#09170D",
            button_bg="#1D3329",
            input_bg="#0E1C16",
            warning="#E6C15A",
            warning_text="#251D08",
        ),
    ]


def available_themes(custom_themes: list[ThemeDefinition]) -> list[ThemeDefinition]:
    theme_map: dict[str, ThemeDefinition] = {theme.id: theme for theme in builtin_themes()}
    for theme in custom_themes:
        theme_map[theme.id] = theme
    return list(theme_map.values())


def resolve_theme_definition(selected_theme_id: str, custom_themes: list[ThemeDefinition]) -> ThemeDefinition:
    theme_map = {theme.id: theme for theme in available_themes(custom_themes)}
    return theme_map.get(selected_theme_id) or builtin_themes()[0]


@dataclass(slots=True)
class ThemePalette:
    window_bg: str
    panel_bg: str
    panel_border: str
    active_pane_border: str
    text_primary: str
    text_muted: str
    title_text: str
    chip_bg: str
    chip_border: str
    chip_text: str
    chip_muted_bg: str
    chip_muted_border: str
    chip_muted_text: str
    clipboard_bg: str
    clipboard_border: str
    clipboard_text: str
    clipboard_cut_bg: str
    clipboard_cut_border: str
    clipboard_cut_text: str
    breadcrumb_bg: str
    breadcrumb_border: str
    breadcrumb_text: str
    breadcrumb_current_bg: str
    breadcrumb_current_border: str
    breadcrumb_current_text: str
    breadcrumb_separator: str
    bookmark_text: str
    bookmark_hover_bg: str
    bookmark_hover_border: str
    bookmark_hover_text: str
    bookmark_active_bg: str
    bookmark_active_border: str
    bookmark_active_text: str
    input_bg: str
    input_text: str
    input_border: str
    selection_bg: str
    selection_text: str
    quick_view_image_bg: str
    quick_view_image_border: str
    combo_popup_bg: str
    combo_popup_border: str
    header_bg: str
    header_text: str
    tree_hover_bg: str
    tree_selected_bg: str
    tree_alternate_bg: str
    thumbnail_item_border: str
    thumbnail_hover_bg: str
    button_bg: str
    button_text: str
    button_border: str
    button_hover_bg: str
    button_hover_border: str
    button_pressed_bg: str
    secondary_button_bg: str
    secondary_button_text: str
    secondary_button_border: str
    secondary_button_active_bg: str
    secondary_button_active_text: str
    secondary_button_active_border: str
    tab_bg: str
    tab_text: str
    tab_border: str
    tab_active_bg: str
    tab_active_text: str
    tab_active_border: str
    tab_hover_bg: str
    tab_hover_text: str
    tab_hover_border: str
    folder_browser_hover_bg: str
    folder_browser_selected_bg: str
    context_bg: str
    context_text: str
    context_border: str
    context_selected_bg: str
    splitter_hover: str
    row_even_bg: str
    row_odd_bg: str
    row_current_bg: str
    row_current_text: str
    row_marked_bg: str
    row_marked_text: str
    row_marked_current_bg: str
    row_marked_current_text: str
    row_drop_target_bg: str
    row_drop_target_text: str
    row_cut_pending_bg: str
    row_cut_pending_text: str


def build_palette(theme: ThemeDefinition) -> ThemePalette:
    accent = _normalize_hex(theme.accent)
    surface_bg = _normalize_hex(theme.surface_bg)
    window_bg = _normalize_hex(theme.window_bg)
    surface_border = _normalize_hex(theme.surface_border)
    text_primary = _normalize_hex(theme.text_primary)
    text_muted = _normalize_hex(theme.text_muted)
    accent_text = _normalize_hex(theme.accent_text)
    button_bg = _normalize_hex(theme.button_bg)
    input_bg = _normalize_hex(theme.input_bg)
    warning = _normalize_hex(theme.warning)
    warning_text = _normalize_hex(theme.warning_text)
    input_border = _mix(surface_border, accent, 0.16)

    return ThemePalette(
        window_bg=window_bg,
        panel_bg=surface_bg,
        panel_border=surface_border,
        active_pane_border=accent,
        text_primary=text_primary,
        text_muted=text_muted,
        title_text=text_primary,
        chip_bg=_mix(accent, surface_bg, 0.68),
        chip_border=_mix(accent, surface_border, 0.30),
        chip_text=accent_text,
        chip_muted_bg=_darken(surface_bg, 0.05),
        chip_muted_border=surface_border,
        chip_muted_text=_lighten(text_muted, 0.12),
        clipboard_bg=_mix(accent, surface_bg, 0.78),
        clipboard_border=_mix(accent, surface_border, 0.40),
        clipboard_text=text_primary,
        clipboard_cut_bg=_mix(warning, surface_bg, 0.78),
        clipboard_cut_border=_mix(warning, surface_border, 0.32),
        clipboard_cut_text=warning_text,
        breadcrumb_bg=_darken(surface_bg, 0.05),
        breadcrumb_border=_mix(surface_border, accent, 0.10),
        breadcrumb_text=_lighten(text_muted, 0.16),
        breadcrumb_current_bg=_mix(accent, surface_bg, 0.82),
        breadcrumb_current_border=_mix(accent, surface_border, 0.30),
        breadcrumb_current_text=text_primary,
        breadcrumb_separator=_lighten(text_muted, 0.06),
        bookmark_text=text_muted,
        bookmark_hover_bg=_mix(accent, surface_bg, 0.85),
        bookmark_hover_border=_mix(accent, surface_border, 0.20),
        bookmark_hover_text=_lighten(text_primary, 0.05),
        bookmark_active_bg=_mix(accent, surface_bg, 0.82),
        bookmark_active_border=_mix(accent, surface_border, 0.30),
        bookmark_active_text=warning,
        input_bg=input_bg,
        input_text=text_primary,
        input_border=input_border,
        selection_bg=_mix(accent, surface_bg, 0.72),
        selection_text=text_primary,
        quick_view_image_bg=input_bg,
        quick_view_image_border=surface_border,
        combo_popup_bg=_lighten(window_bg, 0.04),
        combo_popup_border=_mix(surface_border, accent, 0.16),
        header_bg=_mix(window_bg, surface_bg, 0.55),
        header_text=_lighten(text_muted, 0.08),
        tree_hover_bg=_rgba(accent, 0.22),
        tree_selected_bg=_mix(accent, surface_bg, 0.72),
        tree_alternate_bg=_rgba(surface_border, 0.20),
        thumbnail_item_border=surface_border,
        thumbnail_hover_bg=_rgba(accent, 0.20),
        button_bg=button_bg,
        button_text=text_primary,
        button_border=_mix(surface_border, button_bg, 0.22),
        button_hover_bg=_lighten(button_bg, 0.08),
        button_hover_border=_mix(accent, surface_border, 0.30),
        button_pressed_bg=_darken(button_bg, 0.14),
        secondary_button_bg=_mix(button_bg, surface_bg, 0.45),
        secondary_button_text=_lighten(text_muted, 0.20),
        secondary_button_border=_mix(surface_border, accent, 0.15),
        secondary_button_active_bg=_mix(accent, surface_bg, 0.68),
        secondary_button_active_text=accent_text,
        secondary_button_active_border=_mix(accent, surface_border, 0.30),
        tab_bg=_darken(surface_bg, 0.03),
        tab_text=_lighten(text_muted, 0.14),
        tab_border=_mix(surface_border, accent, 0.08),
        tab_active_bg=_mix(accent, surface_bg, 0.76),
        tab_active_text=text_primary,
        tab_active_border=_mix(accent, surface_border, 0.28),
        tab_hover_bg=_mix(accent, surface_bg, 0.86),
        tab_hover_text=text_primary,
        tab_hover_border=_mix(accent, surface_border, 0.18),
        folder_browser_hover_bg=_rgba(accent, 0.22),
        folder_browser_selected_bg=_rgba(accent, 0.34),
        context_bg=_lighten(window_bg, 0.04),
        context_text=text_primary,
        context_border=_mix(surface_border, accent, 0.16),
        context_selected_bg=_mix(accent, surface_bg, 0.72),
        splitter_hover=_rgba(accent, 0.22),
        row_even_bg=surface_bg,
        row_odd_bg=_mix(surface_bg, window_bg, 0.25),
        row_current_bg=_mix(accent, surface_bg, 0.78),
        row_current_text=text_primary,
        row_marked_bg=_mix(accent, surface_bg, 0.88),
        row_marked_text=_lighten(text_primary, 0.02),
        row_marked_current_bg=_mix(accent, surface_bg, 0.68),
        row_marked_current_text=text_primary,
        row_drop_target_bg=_mix(accent, "#153A2E", 0.35),
        row_drop_target_text=_lighten(text_primary, 0.05),
        row_cut_pending_bg=_mix(warning, surface_bg, 0.80),
        row_cut_pending_text=warning_text,
    )


def build_stylesheet(theme: ThemeDefinition) -> str:
    palette = build_palette(theme)
    font_family = theme.font_family.replace('"', '\\"')
    font_size = max(8, min(24, int(theme.font_size)))
    return f"""
QMainWindow, QWidget, QDialog, QMessageBox {{
    background: {palette.window_bg};
    color: {palette.text_primary};
    font-family: "{font_family}";
    font-size: {font_size}pt;
}}
QFrame#pane,
QFrame#terminalDock,
QFrame#jobsView,
QFrame#quickView,
QFrame#functionKeyBar,
QFrame#dialogCard,
QFrame#terminalSurface,
QFrame#terminalHistoryPanel {{
    background: {palette.panel_bg};
    border: 1px solid {palette.panel_border};
    border-radius: 14px;
}}
QFrame#pane[activePane="true"] {{
    border: 2px solid {palette.active_pane_border};
}}
QLabel#appTitle,
QLabel#paneTitle,
QLabel#terminalTitle {{
    color: {palette.title_text};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#appSubtitle,
QLabel#paneStatus,
QLabel#terminalNote,
QLabel#terminalPath,
QLabel#jobsEmpty,
QLabel#quickViewMeta,
QLabel#quickViewEmpty {{
    color: {palette.text_muted};
}}
QLabel#jobsTitle,
QLabel#quickViewTitle {{
    color: {palette.title_text};
    font-size: 16px;
    font-weight: 700;
}}
QLabel#dialogTitle {{
    color: {palette.title_text};
    font-size: 20px;
    font-weight: 700;
}}
QLabel#dialogSubtitle {{
    color: {palette.text_muted};
    font-size: 13px;
}}
QLabel#dialogHint {{
    color: {palette.text_muted};
    font-size: 12px;
}}
QLabel#dialogSectionLabel {{
    color: {palette.text_primary};
    font-weight: 600;
}}
QLabel#dialogPreviewSample {{
    color: {palette.text_primary};
    font-weight: 600;
    padding: 4px 0px;
}}
QLabel#terminalHistoryTitle,
QLabel#terminalHistorySection {{
    color: {palette.title_text};
    font-weight: 700;
}}
QLabel#terminalHistorySection {{
    font-size: 13px;
}}
QLabel#paneChip,
QLabel#paneChipMuted,
QLabel#clipboardChip,
QLabel#layoutChip,
QLabel#themeBarLabel,
QLabel#terminalActionStatus {{
    padding: 5px 10px;
    border-radius: 999px;
    border: 1px solid {palette.chip_border};
    background: {palette.chip_muted_bg};
    color: {palette.chip_muted_text};
}}
QLabel#paneChip {{
    background: {palette.chip_bg};
    border-color: {palette.chip_border};
    color: {palette.chip_text};
}}
QLabel#paneChipMuted {{
    background: {palette.chip_muted_bg};
    border-color: {palette.chip_muted_border};
    color: {palette.chip_muted_text};
}}
QLabel#clipboardChip {{
    background: {palette.clipboard_bg};
    border-color: {palette.clipboard_border};
    color: {palette.clipboard_text};
}}
QLabel#layoutChip {{
    background: {palette.chip_muted_bg};
    border-color: {palette.chip_muted_border};
    color: {palette.chip_muted_text};
}}
QLabel#clipboardChip[cutMode="true"] {{
    background: {palette.clipboard_cut_bg};
    border-color: {palette.clipboard_cut_border};
    color: {palette.clipboard_cut_text};
}}
QLabel#terminalActionStatus {{
    padding: 4px 8px;
    border-radius: 8px;
    background: {palette.clipboard_cut_bg};
    border-color: {palette.clipboard_cut_border};
    color: {palette.clipboard_cut_text};
    font-size: {max(8, font_size - 1)}pt;
    font-weight: 600;
}}
QFrame#functionKeyBar {{
    background: {_darken(palette.panel_bg, 0.16)};
    border: 1px solid {_mix(palette.panel_border, palette.active_pane_border, 0.08)};
    border-radius: 2px;
    min-height: 48px;
}}
QFrame#functionKeyDivider {{
    background: {_rgba(palette.panel_border, 0.55)};
    border: none;
    min-width: 1px;
    max-width: 1px;
    min-height: 28px;
    max-height: 28px;
}}
QWidget#functionKeyExtras {{
    background: transparent;
}}
QPushButton#functionKeyButton {{
    padding: 0px;
    margin: 0px;
    border-radius: 1px;
    border: 1px solid transparent;
    background: transparent;
    min-height: 34px;
}}
QPushButton#functionKeyButton:hover,
QPushButton#functionKeyButton:focus {{
    background: {_mix(palette.active_pane_border, palette.panel_bg, 0.86)};
    border-color: {_mix(palette.active_pane_border, palette.panel_border, 0.40)};
}}
QPushButton#functionKeyButton:pressed {{
    background: {_mix(palette.active_pane_border, palette.panel_bg, 0.72)};
}}
QLabel#functionKeyShortcut {{
    background: transparent;
    border: none;
    color: {palette.active_pane_border};
    font-family: Consolas;
    font-size: {max(8, font_size - 1)}pt;
    font-weight: 700;
    padding: 0px;
}}
QLabel#functionKeyShortcut[destructive="true"] {{
    color: #F27EA6;
}}
QLabel#functionKeyText {{
    background: transparent;
    border: none;
    color: {_lighten(palette.text_muted, 0.28)};
    font-size: {max(8, font_size - 1)}pt;
    font-weight: 600;
    padding: 0px;
}}
QPushButton#functionKeyButton:hover QLabel#functionKeyText,
QPushButton#functionKeyButton:focus QLabel#functionKeyText {{
    color: {palette.text_primary};
}}
QLabel#layoutChip,
QLabel#clipboardChip,
QPushButton#editThemeButton {{
    min-height: 30px;
    padding: 3px 12px;
    border-radius: 1px;
    border: 1px solid {_mix(palette.panel_border, palette.window_bg, 0.18)};
    background: {_mix(palette.panel_bg, palette.window_bg, 0.32)};
    color: {_lighten(palette.text_muted, 0.10)};
    font-size: {max(8, font_size - 1)}pt;
    font-weight: 500;
}}
QLabel#clipboardChip {{
    color: {palette.text_primary};
    border-color: {palette.clipboard_border};
}}
QLabel#clipboardChip[cutMode="true"] {{
    color: {palette.clipboard_cut_text};
    border-color: {palette.clipboard_cut_border};
}}
QPushButton#editThemeButton:hover {{
    background: {_mix(palette.active_pane_border, palette.panel_bg, 0.88)};
    border-color: {_mix(palette.active_pane_border, palette.panel_border, 0.38)};
    color: {palette.text_primary};
}}
QPushButton#editThemeButton:pressed {{
    background: {_mix(palette.active_pane_border, palette.panel_bg, 0.74)};
}}
QLabel#terminalPath {{
    padding: 2px 4px;
}}
QWidget#breadcrumbHost {{
    background: {palette.breadcrumb_bg};
    border: 1px solid {palette.breadcrumb_border};
    border-radius: 8px;
    min-height: 30px;
}}
QWidget#tabStripHost {{
    background: transparent;
    border-bottom: 1px solid {palette.tab_border};
}}
QPushButton#breadcrumbButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 2px 5px;
    color: {palette.breadcrumb_text};
    font-size: {max(8, font_size - 1)}pt;
    text-align: left;
}}
QPushButton#breadcrumbButton[current="true"] {{
    background: transparent;
    border-color: transparent;
    color: {palette.breadcrumb_text};
    font-weight: 500;
}}
QPushButton#breadcrumbButton:hover {{
    background: {palette.bookmark_hover_bg};
    border-color: {palette.bookmark_hover_border};
}}
QPushButton#breadcrumbNavButton {{
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    margin-right: 4px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {palette.breadcrumb_text};
    font-size: 12px;
    font-weight: 700;
}}
QPushButton#breadcrumbNavButton:hover {{
    background: {palette.bookmark_hover_bg};
    border-color: {palette.bookmark_hover_border};
    color: {palette.bookmark_hover_text};
}}
QPushButton#breadcrumbNavButton:disabled {{
    color: {palette.text_muted};
    background: transparent;
    border-color: transparent;
}}
QLabel#breadcrumbSeparator {{
    color: {palette.breadcrumb_separator};
    font-weight: 700;
    padding: 0 1px;
}}
QPushButton#breadcrumbBookmarkButton {{
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    margin-left: 4px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: {palette.bookmark_text};
    font-size: 14px;
    font-weight: 700;
}}
QPushButton#breadcrumbBookmarkButton:hover {{
    background: {palette.bookmark_hover_bg};
    border-color: {palette.bookmark_hover_border};
    color: {palette.bookmark_hover_text};
}}
QPushButton#breadcrumbBookmarkButton[active="true"] {{
    background: {palette.bookmark_active_bg};
    border-color: {palette.bookmark_active_border};
    color: {palette.bookmark_active_text};
}}
QLineEdit,
QComboBox,
QListWidget,
QTextEdit,
QPlainTextEdit,
QTreeWidget {{
    background: {palette.input_bg};
    color: {palette.input_text};
    border: 1px solid {palette.input_border};
    border-radius: 10px;
    padding: 6px;
    selection-background-color: {palette.selection_bg};
    selection-color: {palette.selection_text};
}}
QTextEdit#terminalOutput,
QPlainTextEdit#terminalOutput,
QPlainTextEdit#quickViewText {{
    font-family: Consolas;
}}
QTextEdit#terminalOutput,
QPlainTextEdit#terminalOutput {{
    border: none;
    border-radius: 14px;
    padding: 12px;
}}
QTextEdit#terminalOutput QScrollBar:vertical,
QPlainTextEdit#terminalOutput QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 6px 2px 6px 2px;
}}
QTextEdit#terminalOutput QScrollBar::handle:vertical,
QPlainTextEdit#terminalOutput QScrollBar::handle:vertical {{
    background: {palette.secondary_button_bg};
    border: 1px solid {palette.secondary_button_border};
    border-radius: 6px;
    min-height: 28px;
}}
QTextEdit#terminalOutput QScrollBar::handle:vertical:hover,
QPlainTextEdit#terminalOutput QScrollBar::handle:vertical:hover {{
    background: {palette.button_hover_bg};
    border-color: {palette.button_hover_border};
}}
QTextEdit#terminalOutput QScrollBar::add-line:vertical,
QTextEdit#terminalOutput QScrollBar::sub-line:vertical,
QTextEdit#terminalOutput QScrollBar::add-page:vertical,
QTextEdit#terminalOutput QScrollBar::sub-page:vertical,
QPlainTextEdit#terminalOutput QScrollBar::add-line:vertical,
QPlainTextEdit#terminalOutput QScrollBar::sub-line:vertical,
QPlainTextEdit#terminalOutput QScrollBar::add-page:vertical,
QPlainTextEdit#terminalOutput QScrollBar::sub-page:vertical {{
    background: transparent;
    border: none;
    height: 0px;
}}
QLineEdit#terminalHistoryFilter {{
    min-height: 30px;
}}
QListWidget#terminalCommandList {{
    min-height: 120px;
    padding: 6px;
}}
QListWidget#terminalCommandList::item {{
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 3px 8px;
    margin: 0px;
    min-height: 22px;
}}
QListWidget#terminalCommandList::item:hover {{
    background: {palette.thumbnail_hover_bg};
    border-color: {palette.button_hover_border};
}}
QListWidget#terminalCommandList::item:selected {{
    background: {palette.tree_selected_bg};
    border-color: {palette.button_hover_border};
    color: {palette.text_primary};
}}
QPlainTextEdit#quickViewText {{
    border-radius: 12px;
}}
QLabel#quickViewImage {{
    background: {palette.quick_view_image_bg};
    border: 1px solid {palette.quick_view_image_border};
    border-radius: 12px;
}}
QComboBox#quickViewSizePicker,
QComboBox#thumbnailSizePicker,
QComboBox#themePicker {{
    min-width: 130px;
    padding: 6px 10px;
    border-radius: 10px;
}}
QComboBox#thumbnailSizePicker {{
    min-width: 92px;
    min-height: 24px;
    padding: 2px 7px;
    border-radius: 7px;
    font-size: {max(8, font_size - 1)}pt;
}}
QComboBox#quickViewSizePicker QAbstractItemView,
QComboBox#thumbnailSizePicker QAbstractItemView,
QComboBox#themePicker QAbstractItemView {{
    background: {palette.combo_popup_bg};
    color: {palette.text_primary};
    border: 1px solid {palette.combo_popup_border};
    selection-background-color: {palette.selection_bg};
}}
QHeaderView::section {{
    background: {palette.header_bg};
    color: {palette.header_text};
    border: none;
    border-bottom: 1px solid {palette.panel_border};
    padding: 8px 10px;
    font-weight: 600;
}}
QTreeWidget::item {{
    height: 32px;
    border-bottom: 1px solid {_rgba(palette.panel_border, 0.35)};
}}
QTreeWidget::item:hover {{
    background: {palette.tree_hover_bg};
}}
QTreeWidget::item:selected,
QListWidget#thumbnailList::item:selected {{
    background: {palette.tree_selected_bg};
}}
QListWidget#thumbnailList {{
    padding: 10px;
}}
QListWidget#thumbnailList::item {{
    border: 1px solid {palette.thumbnail_item_border};
    border-radius: 12px;
    padding: 10px;
    margin: 4px;
}}
QListWidget#thumbnailList::item:hover {{
    background: {palette.thumbnail_hover_bg};
    border-color: {palette.button_hover_border};
}}
QPushButton {{
    background: {palette.button_bg};
    color: {palette.button_text};
    border: 1px solid {palette.button_border};
    border-radius: 10px;
    padding: 6px 12px;
}}
QPushButton#secondaryActionButton {{
    min-height: 24px;
    padding: 2px 7px;
    border-radius: 7px;
    background: {palette.secondary_button_bg};
    color: {palette.secondary_button_text};
    border-color: {palette.secondary_button_border};
    font-size: {max(8, font_size - 1)}pt;
}}
QPushButton#terminalHistoryActionButton {{
    min-width: 26px;
    max-width: 26px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    border-radius: 6px;
    background: {palette.secondary_button_bg};
    color: {palette.secondary_button_text};
    border: 1px solid {palette.secondary_button_border};
    font-size: {max(8, font_size - 1)}pt;
}}
QPushButton#terminalHistoryActionButton:hover {{
    background: {palette.button_hover_bg};
    border-color: {palette.button_hover_border};
    color: {palette.text_primary};
}}
QPushButton#terminalHistoryActionButton:pressed {{
    background: {palette.button_pressed_bg};
}}
QPushButton[dialogRole="primary"] {{
    background: {palette.secondary_button_active_bg};
    color: {palette.secondary_button_active_text};
    border-color: {palette.secondary_button_active_border};
    min-width: 140px;
    padding: 8px 14px;
    font-weight: 600;
}}
QPushButton[dialogRole="primary"]:hover {{
    background: {palette.button_hover_bg};
    border-color: {palette.button_hover_border};
}}
QPushButton[dialogRole="primary"]:focus,
QPushButton[dialogRole="secondary"]:focus {{
    border: 2px solid {palette.active_pane_border};
}}
QPushButton[dialogRole="secondary"] {{
    background: {palette.secondary_button_bg};
    color: {palette.secondary_button_text};
    border-color: {palette.secondary_button_border};
}}
QPushButton#tabButton,
QPushButton#tabAddButton {{
    min-height: 26px;
    padding: 3px 12px;
    border-radius: 0px;
    background: transparent;
    color: {palette.tab_text};
    border: 1px solid transparent;
    border-right-color: {palette.tab_border};
    font-size: {max(8, font_size - 1)}pt;
    font-weight: 500;
}}
QPushButton#tabButton[active="true"] {{
    background: {palette.tab_active_bg};
    color: {palette.tab_active_text};
    border-color: {palette.tab_active_border};
    border-bottom-color: {palette.tab_active_bg};
    border-radius: 12px 12px 0px 0px;
    font-weight: 600;
}}
QPushButton#tabButton:hover {{
    background: {_rgba(palette.active_pane_border, 0.10)};
    color: {palette.tab_hover_text};
    border-color: transparent;
    border-right-color: {palette.tab_border};
}}
QPushButton#tabAddButton {{
    min-width: 28px;
    padding: 3px 0px;
    border-right-color: transparent;
}}
QPushButton#secondaryActionButton[active="true"] {{
    background: {palette.secondary_button_active_bg};
    color: {palette.secondary_button_active_text};
    border-color: {palette.secondary_button_active_border};
}}
QTreeWidget#folderBrowserTree {{
    background: transparent;
    border: none;
    padding: 4px;
}}
QTreeWidget#folderBrowserTree::item {{
    height: 30px;
    border-radius: 8px;
}}
QTreeWidget#folderBrowserTree::item:hover {{
    background: {palette.folder_browser_hover_bg};
}}
QTreeWidget#folderBrowserTree::item:selected {{
    background: {palette.folder_browser_selected_bg};
}}
QMenu#contextMenu {{
    background: {palette.context_bg};
    color: {palette.context_text};
    border: 1px solid {palette.context_border};
    padding: 6px;
}}
QMenu#contextMenu::item {{
    padding: 8px 16px;
    border-radius: 8px;
}}
QMenu#contextMenu::item:selected {{
    background: {palette.context_selected_bg};
}}
QPushButton:hover {{
    background: {palette.button_hover_bg};
    border-color: {palette.button_hover_border};
}}
QPushButton:pressed {{
    background: {palette.button_pressed_bg};
}}
QSplitter::handle {{
    background: transparent;
    width: 10px;
}}
QSplitter::handle:hover {{
    background: {palette.splitter_hover};
}}
QFrame#commandBar {{
    background: {palette.panel_bg};
    border: 1px solid {palette.panel_border};
    border-radius: 10px;
}}
QWidget#commandBarInputRow {{
    background: transparent;
}}
QLabel#commandBarPrompt {{
    color: {palette.text_muted};
    font-family: Consolas, monospace;
    font-size: {font_size}pt;
    padding: 0px 2px;
}}
QLineEdit#commandBarInput {{
    background: transparent;
    border: none;
    border-radius: 0px;
    color: {palette.text_primary};
    font-family: Consolas, monospace;
    font-size: {font_size}pt;
    padding: 2px 4px;
    selection-background-color: {palette.selection_bg};
    selection-color: {palette.selection_text};
}}
QLineEdit#commandBarInput:focus {{
    background: {_rgba(palette.active_pane_border, 0.07)};
    border-radius: 6px;
}}
QFrame#commandBarOutput {{
    background: {_darken(palette.panel_bg, 0.20)};
    border: none;
    border-bottom: 1px solid {palette.panel_border};
    border-radius: 0px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}}
QLabel#commandBarOutputCommand {{
    color: {palette.text_muted};
    font-family: Consolas, monospace;
    font-size: {max(8, font_size - 1)}pt;
}}
QLabel#commandBarOutputText {{
    color: {palette.text_primary};
    font-family: Consolas, monospace;
    font-size: {font_size}pt;
}}
QPushButton#commandBarCloseButton {{
    background: {palette.secondary_button_bg};
    border: 1px solid {palette.secondary_button_border};
    border-radius: 5px;
    color: {palette.text_primary};
    font-size: {font_size}pt;
    font-weight: 600;
    padding: 0px;
}}
QPushButton#commandBarCloseButton:hover {{
    background: {palette.button_hover_bg};
    border-color: {palette.button_hover_border};
    color: {palette.text_primary};
}}
QPushButton#commandBarCloseButton:pressed {{
    background: {palette.button_pressed_bg};
}}
"""
