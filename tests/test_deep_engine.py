from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from multipane_commander.ui.deep_terminal import engine as engine_module
from multipane_commander.ui.deep_terminal.engine import (
    ENGINE_CLASSIC,
    ENGINE_DEEP,
    create_terminal_dock,
    normalize_engine,
    resolve_engine,
)
from multipane_commander.ui.terminal_dock import TerminalDock


_APP: QApplication | None = None


@pytest.fixture(autouse=True)
def _offscreen_app(monkeypatch) -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    from multipane_commander.ui.terminal_surface import TerminalSurface

    monkeypatch.setattr(
        "multipane_commander.ui.terminal_dock.WEB_TERMINAL_AVAILABLE",
        False,
    )
    monkeypatch.setattr(
        "multipane_commander.ui.terminal_dock.create_terminal_surface",
        lambda parent=None, **_kwargs: TerminalSurface(),
    )
    return _APP


class SentinelDock:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class ExplodingDock:
    def __init__(self, **kwargs) -> None:
        raise RuntimeError("no WebEngine")


def _kwargs(tmp_path: Path) -> dict:
    return {
        "initial_directory": tmp_path,
        "visible": False,
        "follow_active_pane": True,
        "experimental_pty": False,
        "recent_commands": [],
        "bookmarked_commands": [],
        "history_panel_visible": False,
    }


def test_normalize_engine_falls_back_to_deep() -> None:
    assert normalize_engine("deep") == ENGINE_DEEP
    assert normalize_engine("classic") == ENGINE_CLASSIC
    assert normalize_engine(None) == ENGINE_DEEP
    assert normalize_engine("bogus") == ENGINE_DEEP


def test_resolve_engine_falls_back_to_classic_without_webengine(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "deep_terminal_available", lambda: False)

    assert resolve_engine("deep") == ENGINE_CLASSIC
    assert resolve_engine("classic") == ENGINE_CLASSIC


def test_resolve_engine_keeps_deep_when_available(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "deep_terminal_available", lambda: True)

    assert resolve_engine("deep") == ENGINE_DEEP


def test_create_terminal_dock_builds_deep_when_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "DeepTerminalDock", SentinelDock)
    monkeypatch.setattr(engine_module, "deep_terminal_available", lambda: True)

    dock = create_terminal_dock(engine="deep", **_kwargs(tmp_path))

    assert isinstance(dock, SentinelDock)
    assert dock.kwargs["initial_directory"] == tmp_path


def test_create_terminal_dock_falls_back_when_deep_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "DeepTerminalDock", ExplodingDock)
    monkeypatch.setattr(engine_module, "deep_terminal_available", lambda: True)

    dock = create_terminal_dock(engine="deep", **_kwargs(tmp_path))

    assert isinstance(dock, TerminalDock)


def test_create_terminal_dock_honours_classic_engine(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "DeepTerminalDock", SentinelDock)

    dock = create_terminal_dock(engine="classic", **_kwargs(tmp_path))

    assert isinstance(dock, TerminalDock)
