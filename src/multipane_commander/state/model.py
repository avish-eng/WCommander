from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class TabState:
    title: str
    path: Path
    navigation_history: list[Path] = field(default_factory=list)
    navigation_index: int = -1


@dataclass(slots=True)
class PaneState:
    title: str
    tabs: list[TabState] = field(default_factory=list)
    active_tab_index: int = 0
    quick_view_enabled: bool = False
    thumbnail_mode_enabled: bool = False
    quick_view_size_preset: str = "Comfortable"
    thumbnail_size_preset: str = "Medium"


@dataclass(slots=True)
class LayoutState:
    active_pane_index: int = 0
    layout_mode: str = "stacked"
    pane_splitter_sizes: list[int] = field(default_factory=list)
    content_splitter_sizes: list[int] = field(default_factory=list)
    side_by_side_splitter_sizes: list[int] = field(default_factory=list)
    terminal_maximized: bool = False


@dataclass(slots=True)
class WindowState:
    width: int = 1280
    height: int = 860
    is_maximized: bool = False


@dataclass(slots=True)
class AppState:
    panes: list[PaneState]
    bookmarks: list[Path] = field(default_factory=list)
    layout: LayoutState = field(default_factory=LayoutState)
    window: WindowState = field(default_factory=WindowState)
