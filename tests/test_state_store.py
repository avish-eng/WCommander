import json
from pathlib import Path

from multipane_commander.state.model import AppState, PaneState, TabState
from multipane_commander.state.store import load_state, save_state


def test_state_store_persists_view_size_presets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    root = tmp_path / "workspace"
    root.mkdir()
    left = root / "left"
    right = root / "right"
    left.mkdir()
    right.mkdir()

    state = AppState(
        panes=[
            PaneState(
                title="Left",
                tabs=[TabState(title="left", path=left)],
                quick_view_enabled=True,
                thumbnail_mode_enabled=False,
                quick_view_size_preset="Large",
                thumbnail_size_preset="Small",
            ),
            PaneState(
                title="Right",
                tabs=[TabState(title="right", path=right)],
                quick_view_enabled=False,
                thumbnail_mode_enabled=True,
                quick_view_size_preset="Compact",
                thumbnail_size_preset="Large",
            ),
        ],
        bookmarks=[root / "saved-bookmark", root / "missing-bookmark"],
    )
    state.layout.active_pane_index = 1
    state.layout.layout_mode = "terminal_right"
    state.layout.pane_splitter_sizes = [720, 1080]
    state.layout.content_splitter_sizes = [880, 280]
    state.layout.side_by_side_splitter_sizes = [960, 840]
    state.layout.terminal_maximized = True
    state.window.width = 1660
    state.window.height = 1010
    state.window.is_maximized = True

    save_state(state)
    loaded = load_state()

    assert loaded.panes[0].quick_view_enabled is True
    assert loaded.panes[0].thumbnail_mode_enabled is False
    assert loaded.panes[0].quick_view_size_preset == "Large"
    assert loaded.panes[0].thumbnail_size_preset == "Small"
    assert loaded.panes[1].quick_view_enabled is False
    assert loaded.panes[1].thumbnail_mode_enabled is True
    assert loaded.panes[1].quick_view_size_preset == "Compact"
    assert loaded.panes[1].thumbnail_size_preset == "Large"
    assert loaded.bookmarks == [root / "saved-bookmark", root / "missing-bookmark"]
    assert loaded.layout.active_pane_index == 1
    assert loaded.layout.layout_mode == "terminal_right"
    assert loaded.layout.pane_splitter_sizes == [720, 1080]
    assert loaded.layout.content_splitter_sizes == [880, 280]
    assert loaded.layout.side_by_side_splitter_sizes == [960, 840]
    assert loaded.layout.terminal_maximized is True
    assert loaded.window.width == 1660
    assert loaded.window.height == 1010
    assert loaded.window.is_maximized is True


def test_state_store_handles_malformed_numeric_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    root = tmp_path / "workspace"
    root.mkdir()
    left = root / "left"
    right = root / "right"
    left.mkdir()
    right.mkdir()

    state_path = tmp_path / "MultiPaneCommander" / "state.json"
    state_path.parent.mkdir()
    state_path.write_text(
        json.dumps(
            {
                "active_pane_index": "999",
                "layout_mode": "",
                "pane_splitter_sizes": ["wide", None, 320],
                "content_splitter_sizes": ["tall", 240],
                "side_by_side_splitter_sizes": ["narrow", 360],
                "window": {"width": "wide", "height": None},
                "panes": [
                    {
                        "title": "Left",
                        "active_tab_index": "bad",
                        "tabs": [{"title": "left", "path": str(left)}],
                    },
                    {
                        "title": "Right",
                        "active_tab_index": 20,
                        "tabs": [{"title": "right", "path": str(right)}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_state()

    assert loaded.layout.active_pane_index == 1
    assert loaded.layout.layout_mode == "stacked"
    assert loaded.layout.pane_splitter_sizes == [320]
    assert loaded.layout.content_splitter_sizes == [240]
    assert loaded.layout.side_by_side_splitter_sizes == [360]
    assert loaded.window.width >= 1000
    assert loaded.window.height >= 700
    assert loaded.panes[0].active_tab_index == 0
    assert loaded.panes[1].active_tab_index == 0


def test_state_store_falls_back_when_payload_shape_is_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    state_path = tmp_path / "MultiPaneCommander" / "state.json"
    state_path.parent.mkdir()
    state_path.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")

    loaded = load_state()

    assert len(loaded.panes) == 2
    assert loaded.layout.active_pane_index == 0
    assert loaded.bookmarks == []
