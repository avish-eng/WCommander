from __future__ import annotations

import json
from pathlib import Path

from multipane_commander.platform import app_data_dir
from multipane_commander.state.model import AppState, LayoutState, PaneState, TabState, WindowState


def _state_file_path() -> Path:
    return app_data_dir() / "state.json"


def _default_state() -> AppState:
    default_path = Path.home()
    return AppState(
        panes=[
            PaneState(
                title="Left",
                tabs=[TabState(title=default_path.name or str(default_path), path=default_path)],
            ),
            PaneState(
                title="Right",
                tabs=[TabState(title=default_path.name or str(default_path), path=default_path)],
            ),
        ],
        bookmarks=[],
    )


def load_state() -> AppState:
    """Load persisted state if available, otherwise use defaults."""
    state_path = _state_file_path()
    default_state = _default_state()
    if not state_path.exists():
        return default_state

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state
    if not isinstance(payload, dict):
        return default_state

    panes: list[PaneState] = []
    panes_payload = payload.get("panes", [])
    if not isinstance(panes_payload, list):
        panes_payload = []

    for index, pane_payload in enumerate(panes_payload):
        if not isinstance(pane_payload, dict):
            continue
        tabs_payload = pane_payload.get("tabs", [])
        if not isinstance(tabs_payload, list):
            tabs_payload = []
        tabs: list[TabState] = []
        for tab_payload in tabs_payload:
            if not isinstance(tab_payload, dict):
                continue
            path_str = tab_payload.get("path")
            if not path_str:
                continue
            path = Path(path_str)
            if not path.exists():
                continue
            tabs.append(
                TabState(
                    title=str(tab_payload.get("title") or path.name or str(path)),
                    path=path,
                )
            )

        if not tabs:
            path_str = pane_payload.get("path")
            if not path_str:
                continue
            path = Path(path_str)
            if not path.exists():
                default_index = min(index, len(default_state.panes) - 1)
                path = default_state.panes[default_index].tabs[0].path
            tabs = [TabState(title=path.name or str(path), path=path)]

        default_pane = default_state.panes[min(index, len(default_state.panes) - 1)]
        panes.append(
            PaneState(
                title=str(pane_payload.get("title") or f"Pane {index + 1}"),
                tabs=tabs,
                active_tab_index=_clamp_int(
                    pane_payload.get("active_tab_index", 0),
                    minimum=0,
                    maximum=len(tabs) - 1,
                    default=0,
                ),
                quick_view_enabled=bool(pane_payload.get("quick_view_enabled", False)),
                thumbnail_mode_enabled=bool(pane_payload.get("thumbnail_mode_enabled", False)),
                quick_view_size_preset=str(
                    pane_payload.get(
                        "quick_view_size_preset",
                        default_pane.quick_view_size_preset,
                    )
                ),
                thumbnail_size_preset=str(
                    pane_payload.get(
                        "thumbnail_size_preset",
                        default_pane.thumbnail_size_preset,
                    )
                ),
            )
        )

    if not panes:
        panes = default_state.panes

    bookmarks_payload = payload.get("bookmarks", [])
    if not isinstance(bookmarks_payload, list):
        bookmarks_payload = []
    bookmarks = [
        Path(path_str)
        for path_str in bookmarks_payload
        if isinstance(path_str, str) and path_str.strip()
    ]

    window_payload = payload.get("window", {})
    if not isinstance(window_payload, dict):
        window_payload = {}
    active_pane_index = _clamp_int(
        payload.get("active_pane_index", 0),
        minimum=0,
        maximum=len(panes) - 1,
        default=0,
    )
    return AppState(
        panes=panes,
        bookmarks=bookmarks,
        layout=LayoutState(
            active_pane_index=active_pane_index,
            layout_mode=str(payload.get("layout_mode") or "stacked"),
            pane_splitter_sizes=[
                parsed
                for size in _list_payload(payload.get("pane_splitter_sizes", []))
                for parsed in [_safe_int(size, 0)]
                if parsed > 0
            ],
            content_splitter_sizes=[
                parsed
                for size in _list_payload(payload.get("content_splitter_sizes", []))
                for parsed in [_safe_int(size, 0)]
                if parsed > 0
            ],
            side_by_side_splitter_sizes=[
                parsed
                for size in _list_payload(payload.get("side_by_side_splitter_sizes", []))
                for parsed in [_safe_int(size, 0)]
                if parsed > 0
            ],
            terminal_maximized=bool(payload.get("terminal_maximized", False)),
        ),
        window=WindowState(
            width=max(
                1000,
                _safe_int(window_payload.get("width"), default_state.window.width),
            ),
            height=max(
                700,
                _safe_int(window_payload.get("height"), default_state.window.height),
            ),
            is_maximized=bool(window_payload.get("is_maximized", False)),
        ),
    )


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_int(value: object, *, minimum: int, maximum: int, default: int) -> int:
    if maximum < minimum:
        return default
    parsed = _safe_int(value, default)
    return max(minimum, min(parsed, maximum))


def _list_payload(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def save_state(state: AppState) -> None:
    state_path = _state_file_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "window": {
            "width": state.window.width,
            "height": state.window.height,
            "is_maximized": state.window.is_maximized,
        },
        "bookmarks": [str(path) for path in state.bookmarks],
        "active_pane_index": state.layout.active_pane_index,
        "layout_mode": state.layout.layout_mode,
        "pane_splitter_sizes": state.layout.pane_splitter_sizes,
        "content_splitter_sizes": state.layout.content_splitter_sizes,
        "side_by_side_splitter_sizes": state.layout.side_by_side_splitter_sizes,
        "terminal_maximized": state.layout.terminal_maximized,
        "panes": [
            {
                "title": pane.title,
                "path": str(pane.tabs[pane.active_tab_index].path),
                "active_tab_index": pane.active_tab_index,
                "quick_view_enabled": pane.quick_view_enabled,
                "thumbnail_mode_enabled": pane.thumbnail_mode_enabled,
                "quick_view_size_preset": pane.quick_view_size_preset,
                "thumbnail_size_preset": pane.thumbnail_size_preset,
                "tabs": [
                    {
                        "title": tab.title,
                        "path": str(tab.path),
                    }
                    for tab in pane.tabs
                ],
            }
            for pane in state.panes
        ],
    }
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
