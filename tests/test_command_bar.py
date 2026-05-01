from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from multipane_commander.ui.command_bar import CommandBar, OutputPanel


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def _make_bar() -> CommandBar:
    _qapp()
    bar = CommandBar()
    bar.show()
    return bar


def _key(key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier, text: str = "") -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)


def _press(bar: CommandBar, key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier, text: str = "") -> None:
    bar._input.setFocus()
    QApplication.sendEvent(bar._input, _key(key, modifiers, text))


# ---------------------------------------------------------------------------
# cd navigation
# ---------------------------------------------------------------------------

def test_cd_navigation(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.set_cwd(tmp_path)

    sub = tmp_path / "subdir"
    sub.mkdir()

    navigated: list[Path] = []
    bar.navigate_requested.connect(navigated.append)

    bar._input.setText(f"cd subdir")
    _press(bar, Qt.Key.Key_Return)

    assert len(navigated) == 1
    assert navigated[0] == sub


def test_cd_no_arg_goes_home(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.set_cwd(tmp_path)

    navigated: list[Path] = []
    bar.navigate_requested.connect(navigated.append)

    bar._input.setText("cd")
    _press(bar, Qt.Key.Key_Return)

    assert len(navigated) == 1
    assert navigated[0] == Path.home().resolve()


def test_cd_dotdot(tmp_path: Path) -> None:
    sub = tmp_path / "child"
    sub.mkdir()
    bar = _make_bar()
    bar.set_cwd(sub)

    navigated: list[Path] = []
    bar.navigate_requested.connect(navigated.append)

    bar._input.setText("cd ..")
    _press(bar, Qt.Key.Key_Return)

    assert len(navigated) == 1
    assert navigated[0] == tmp_path.resolve()


def test_cd_nonexistent_shows_error(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.set_cwd(tmp_path)

    navigated: list[Path] = []
    bar.navigate_requested.connect(navigated.append)

    bar._input.setText("cd /this/does/not/exist/at/all")
    _press(bar, Qt.Key.Key_Return)

    assert len(navigated) == 0
    assert bar.output_panel.isVisible()


def test_cd_does_not_spawn_subprocess(tmp_path: Path, monkeypatch) -> None:
    bar = _make_bar()
    bar.set_cwd(tmp_path)
    sub = tmp_path / "d"
    sub.mkdir()

    spawned = []
    original = bar._execute_inline
    def patched():
        spawned.append(True)
        original()
    monkeypatch.setattr(bar, "_execute_inline", patched)

    # Typing cd should intercept before execute_inline
    bar._input.setText("cd d")
    _press(bar, Qt.Key.Key_Return)
    # _execute_inline is NOT the cd path — cd is handled in _handle_cd via _execute_inline
    # What we really verify is that no QProcess was spawned
    assert bar._process is None


# ---------------------------------------------------------------------------
# Inline execution
# ---------------------------------------------------------------------------

def test_inline_execution_output(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.set_cwd(tmp_path)

    bar._input.setText("echo hello")
    _press(bar, Qt.Key.Key_Return)

    # Wait for the async process to finish
    import time
    deadline = time.time() + 5
    while not bar.output_panel.isVisible() and time.time() < deadline:
        QApplication.processEvents()

    assert bar.output_panel.isVisible()
    assert "hello" in bar.output_panel._text.text()


def test_inline_refreshes_file_list(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.set_cwd(tmp_path)

    refreshed: list[bool] = []
    bar.refresh_requested.connect(lambda: refreshed.append(True))

    bar._input.setText("echo noop")
    _press(bar, Qt.Key.Key_Return)

    import time
    deadline = time.time() + 5
    while not refreshed and time.time() < deadline:
        QApplication.processEvents()

    assert refreshed


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def test_history_up_down(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.set_cwd(tmp_path)

    # Add commands to history directly
    bar._add_to_history("echo first")
    bar._add_to_history("echo second")
    bar._add_to_history("echo third")

    # Up once → most recent
    _press(bar, Qt.Key.Key_Up)
    assert bar._input.text() == "echo third"

    # Up again → second
    _press(bar, Qt.Key.Key_Up)
    assert bar._input.text() == "echo second"

    # Down → back to third
    _press(bar, Qt.Key.Key_Down)
    assert bar._input.text() == "echo third"

    # Down from top → clear
    _press(bar, Qt.Key.Key_Down)
    assert bar._input.text() == ""


# ---------------------------------------------------------------------------
# Esc behaviour
# ---------------------------------------------------------------------------

def test_esc_dismisses_output(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.output_panel.show_output("echo hi", "hi")
    assert bar.output_panel.isVisible()

    _press(bar, Qt.Key.Key_Escape)
    assert not bar.output_panel.isVisible()


def test_esc_clears_input(tmp_path: Path) -> None:
    bar = _make_bar()
    bar._input.setText("some command")

    _press(bar, Qt.Key.Key_Escape)
    assert bar._input.text() == ""


def test_esc_clears_focus_when_empty(tmp_path: Path) -> None:
    bar = _make_bar()
    bar._input.setFocus()
    bar._input.setText("")

    _press(bar, Qt.Key.Key_Escape)
    assert not bar._input.hasFocus()


# ---------------------------------------------------------------------------
# Ctrl+G / focus
# ---------------------------------------------------------------------------

def test_focus_input_sets_focus(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.focus_input()
    QApplication.processEvents()
    assert bar._input.hasFocus()


def test_focus_input_with_text(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.focus_input(initial_text="git")
    assert bar._input.text() == "git"


# ---------------------------------------------------------------------------
# Prompt label
# ---------------------------------------------------------------------------

def test_cwd_updates_prompt(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.set_cwd(tmp_path)
    assert bar._prompt.text() == f"{tmp_path.name}>"


def test_cwd_updates_on_set(tmp_path: Path) -> None:
    sub = tmp_path / "projects"
    sub.mkdir()
    bar = _make_bar()
    bar.set_cwd(sub)
    assert bar._prompt.text() == "projects>"
    assert bar._cwd == sub


# ---------------------------------------------------------------------------
# Shift+Enter → escalate
# ---------------------------------------------------------------------------

def test_shift_enter_emits_escalate(tmp_path: Path) -> None:
    bar = _make_bar()
    bar.set_cwd(tmp_path)

    escalated: list[tuple[str, str]] = []
    bar.escalate_requested.connect(lambda cwd, cmd: escalated.append((cwd, cmd)))

    bar._input.setText("vim README.md")
    _press(bar, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)

    assert len(escalated) == 1
    assert escalated[0][0] == str(tmp_path)
    assert escalated[0][1] == "vim README.md"
    assert bar._input.text() == ""
