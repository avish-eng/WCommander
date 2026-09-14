from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from deep_terminal_helpers import FakeDeepSession
from multipane_commander.bootstrap import AppContext
from multipane_commander.config.load import load_config
from multipane_commander.config.model import AppConfig
from multipane_commander.state.model import AppState, LayoutState, PaneState, TabState, WindowState
from multipane_commander.ui.deep_terminal.dock import DeepTerminalDock
from multipane_commander.ui.deep_terminal.surface import DeepTerminalSurface
from multipane_commander.ui.main_window import MainWindow
from multipane_commander.ui.terminal_dock import TerminalDock
from multipane_commander.ui.terminal_surface import TerminalSurface


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def _patch_terminals(monkeypatch) -> list[FakeDeepSession]:
    sessions: list[FakeDeepSession] = []

    def deep_surface(self) -> DeepTerminalSurface:
        return DeepTerminalSurface(self, web_view_factory=lambda parent: QWidget(parent))

    def deep_session(self, path: Path) -> FakeDeepSession:
        session = FakeDeepSession(path, getattr(self, "_prefer_pty", True))
        sessions.append(session)
        return session

    def classic_session(self, path: Path) -> FakeDeepSession:
        session = FakeDeepSession(path, False)
        sessions.append(session)
        return session

    monkeypatch.setattr(DeepTerminalDock, "_build_surface", deep_surface)
    monkeypatch.setattr(DeepTerminalDock, "_build_session", deep_session)
    monkeypatch.setattr(TerminalDock, "_build_session", classic_session)
    monkeypatch.setattr(
        "multipane_commander.ui.terminal_dock.create_terminal_surface",
        lambda parent=None: TerminalSurface(),
    )
    monkeypatch.setattr(
        "multipane_commander.ui.terminal_dock.WEB_TERMINAL_AVAILABLE",
        False,
    )
    return sessions


def _make_window(tmp_path: Path) -> MainWindow:
    _qapp()
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir(exist_ok=True)
    right.mkdir(exist_ok=True)
    state = AppState(
        panes=[
            PaneState(title="Left", tabs=[TabState(title="left", path=left)]),
            PaneState(title="Right", tabs=[TabState(title="right", path=right)]),
        ],
        bookmarks=[],
        layout=LayoutState(active_pane_index=0, layout_mode="stacked"),
        window=WindowState(width=1280, height=860, is_maximized=False),
    )
    config = AppConfig()
    config.show_terminal = False
    config.terminal.engine = "deep"
    window = MainWindow(context=AppContext(config=config, state=state))
    window.show()
    QApplication.processEvents()
    return window


def test_main_window_uses_deep_terminal_by_default(tmp_path: Path, monkeypatch) -> None:
    sessions = _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        assert isinstance(window.terminal_dock, DeepTerminalDock)
        assert window._terminal_dock_engine() == "deep"
        assert len(sessions) == 1
        assert sessions[0].starts == 0
    finally:
        window.close()


def test_main_window_deep_terminal_starts_on_toggle(tmp_path: Path, monkeypatch) -> None:
    sessions = _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        assert not window.terminal_dock.isVisible()

        window._toggle_terminal()
        QApplication.processEvents()

        assert window.terminal_dock.isVisible()
        assert len(sessions) == 1
        assert sessions[0].starts == 1
        assert window.context.config.show_terminal is True
        assert load_config().show_terminal is True
    finally:
        window.close()


def test_main_window_deep_terminal_follows_active_pane(tmp_path: Path, monkeypatch) -> None:
    sessions = _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        target = tmp_path / "target"
        target.mkdir()
        sessions[0].directories.clear()

        window._sync_terminal_to_pane_directory(window._active_pane(), target)

        assert sessions[0].directories == [target]
    finally:
        window.close()


def test_main_window_routes_terminal_clipboard_when_focused(tmp_path: Path, monkeypatch) -> None:
    _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        copied: list[bool] = []
        pasted: list[bool] = []
        window.terminal_dock.output.copy = lambda: copied.append(True)
        window.terminal_dock.output.paste_from_clipboard = lambda: pasted.append(True)
        monkeypatch.setattr(window, "_terminal_has_focus", lambda: True)

        window._copy_selection_to_clipboard()
        window._paste_clipboard_into_active_pane()

        assert copied == [True]
        assert pasted == [True]
    finally:
        window.close()


def test_main_window_injects_text_into_deep_terminal(tmp_path: Path, monkeypatch) -> None:
    _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        injected: list[tuple[str, bool]] = []
        window.terminal_dock.output.inject_command = (
            lambda command, run: injected.append((command, run))
        )

        window._inject_into_terminal("my file.txt")

        assert window.terminal_dock.isVisible()
        assert injected == [("my file.txt ", False)]
    finally:
        window.close()


def test_main_window_switches_between_deep_and_classic_engines(tmp_path: Path, monkeypatch) -> None:
    _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        window._set_terminal_engine("classic")
        QApplication.processEvents()

        assert isinstance(window.terminal_dock, TerminalDock)
        assert not isinstance(window.terminal_dock, DeepTerminalDock)
        assert window.context.config.terminal.engine == "classic"
        assert load_config().terminal.engine == "classic"
        assert window.content_splitter.widget(1) is window.terminal_dock

        window._set_terminal_engine("deep")
        QApplication.processEvents()

        assert isinstance(window.terminal_dock, DeepTerminalDock)
        assert window.context.config.terminal.engine == "deep"
        assert load_config().terminal.engine == "deep"
        assert window.content_splitter.widget(1) is window.terminal_dock
    finally:
        window.close()


def test_main_window_engine_switch_is_a_noop_for_same_engine(tmp_path: Path, monkeypatch) -> None:
    sessions = _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        dock = window.terminal_dock

        window._set_terminal_engine("deep")

        assert window.terminal_dock is dock
        assert len(sessions) == 1
    finally:
        window.close()


def test_main_window_persists_terminal_history_from_deep_dock(tmp_path: Path, monkeypatch) -> None:
    _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        dock = window.terminal_dock
        dock._remember_command("git status")

        assert load_config().terminal.recent_commands == ["git status"]
    finally:
        window.close()
