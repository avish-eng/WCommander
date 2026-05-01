from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from multipane_commander.config.model import AiConfig
from multipane_commander.services.ai.runner import AgentRunner
from multipane_commander.services.ai.sandbox import PaneRoots
from multipane_commander.ui.ai_palette import AiPaletteDialog

_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    _APP = QApplication([])
    return _APP


def _wait_until(predicate, timeout_ms: int = 5000) -> None:
    app = _qapp()
    deadline_hit = threading.Event()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: deadline_hit.set())
    timer.start(timeout_ms)
    while not predicate() and not deadline_hit.is_set():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    timer.stop()
    if not predicate():
        raise AssertionError(f"timed out after {timeout_ms}ms waiting for predicate")


@pytest.fixture
def pane_roots(tmp_path: Path) -> PaneRoots:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    return PaneRoots(left=left, right=right)


@pytest.fixture
def cli_present(monkeypatch, tmp_path):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n")
    from multipane_commander.services.ai import availability as av
    monkeypatch.setattr(av.shutil, "which", lambda _n: str(fake))


def _make_query(messages: list[Any]):
    async def fake_query(*, prompt: str, options: Any, transport: Any = None) -> AsyncIterator[Any]:
        for msg in messages:
            await asyncio.sleep(0)
            yield msg

    return fake_query


def _result_msg() -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=5,
        is_error=False,
        num_turns=1,
        session_id="fake",
        result=None,
        usage={"input_tokens": 10, "output_tokens": 5},
        total_cost_usd=0.0001,
    )


def test_palette_creates_without_crash(pane_roots) -> None:
    _qapp()
    runner = AgentRunner(AiConfig(), query_fn=_make_query([]))
    dialog = AiPaletteDialog(runner, pane_roots)
    assert dialog is not None
    dialog.close()


def test_palette_send_streams_text_and_completes(cli_present, pane_roots) -> None:
    _qapp()
    messages = [
        AssistantMessage(content=[TextBlock(text="Hello "), TextBlock(text="world")], model="m"),
        _result_msg(),
    ]
    runner = AgentRunner(AiConfig(), query_fn=_make_query(messages))
    dialog = AiPaletteDialog(runner, pane_roots)
    dialog.show()

    dialog._input.setText("test question")
    dialog._send()

    _wait_until(lambda: "Done" in dialog._status.text())
    assert "Hello world" in dialog._text_view.toPlainText()
    assert dialog._session_id is None
    assert dialog._send_btn.isEnabled()
    dialog.close()


def test_palette_cancel_stops_session(cli_present, pane_roots) -> None:
    _qapp()
    started = threading.Event()

    async def slow(*, prompt, options, transport=None):
        yield AssistantMessage(content=[TextBlock(text="tick")], model="m")
        started.set()
        for _ in range(30):
            await asyncio.sleep(0.05)
            yield AssistantMessage(content=[TextBlock(text=".")], model="m")
        yield _result_msg()

    runner = AgentRunner(AiConfig(), query_fn=slow)
    dialog = AiPaletteDialog(runner, pane_roots)
    dialog.show()
    dialog._input.setText("test")
    dialog._send()

    _wait_until(started.is_set, timeout_ms=2000)
    assert dialog._session_id is not None
    dialog._cancel()
    _wait_until(lambda: "Cancelled" in dialog._status.text(), timeout_ms=5000)
    assert dialog._session_id is None
    dialog.close()


def test_palette_escape_hides_dialog(pane_roots) -> None:
    _qapp()
    runner = AgentRunner(AiConfig(), query_fn=_make_query([]))
    dialog = AiPaletteDialog(runner, pane_roots)
    dialog.show()
    assert dialog.isVisible()

    event = QKeyEvent(QEvent.Type.KeyPress, 0x01000000, Qt.KeyboardModifier.NoModifier)
    dialog.keyPressEvent(event)
    assert not dialog.isVisible()
    dialog.close()


def test_palette_update_context_replaces_roots(pane_roots, tmp_path) -> None:
    _qapp()
    runner = AgentRunner(AiConfig(), query_fn=_make_query([]))
    dialog = AiPaletteDialog(runner, pane_roots)
    new_left = tmp_path / "new_left"
    new_left.mkdir()
    new_right = tmp_path / "new_right"
    new_right.mkdir()
    new_roots = PaneRoots(left=new_left, right=new_right)
    dialog.update_context(new_roots)
    assert dialog._pane_roots is new_roots
    dialog.close()


@pytest.fixture(autouse=True)
def _drain_pending_events():
    yield
    app = QCoreApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
