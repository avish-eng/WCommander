from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from multipane_commander.config.model import AiConfig
from multipane_commander.services.ai.events import (
    AiResult,
    ToolCallEnd,
    ToolCallStart,
)
from multipane_commander.services.ai.runner import AgentRunner, AiUnavailable
from multipane_commander.services.ai.sandbox import PaneRoots

_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    _APP = QApplication([])
    return _APP


def _wait_until(predicate, timeout_ms: int = 5000) -> None:
    """Spin Qt's event loop until `predicate()` is true or timeout fires."""
    app = _qapp()
    deadline_hit = threading.Event()

    def on_timeout() -> None:
        deadline_hit.set()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(on_timeout)
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
    """Make detect_claude_cli() report 'available' so start_session proceeds."""
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n")
    from multipane_commander.services.ai import availability as av
    monkeypatch.setattr(av.shutil, "which", lambda _n: str(fake))


def _make_query(messages: list[Any]):
    """Wrap a list of SDK messages as a fake `query` function.

    Matches the real signature: `query(*, prompt, options, transport=None)`
    returns an async iterator of messages.
    """

    async def fake_query(*, prompt: str, options: Any, transport: Any = None) -> AsyncIterator[Any]:
        for msg in messages:
            await asyncio.sleep(0)  # yield so cancel checks have a chance
            yield msg

    return fake_query


def _result_message(*, is_error: bool = False, error: str | None = None) -> ResultMessage:
    return ResultMessage(
        subtype="success" if not is_error else "error",
        duration_ms=10,
        duration_api_ms=5,
        is_error=is_error,
        num_turns=1,
        session_id="fake-sdk-session",
        result=error,
        usage={"input_tokens": 100, "output_tokens": 20},
        total_cost_usd=0.0001,
    )


def test_emits_text_then_completes(cli_present, pane_roots) -> None:
    _qapp()
    messages = [
        AssistantMessage(
            content=[TextBlock(text="Hello, "), TextBlock(text="world!")],
            model="claude-sonnet-4-6",
        ),
        _result_message(),
    ]
    runner = AgentRunner(AiConfig(), query_fn=_make_query(messages))

    events: list[Any] = []
    results: list[AiResult] = []
    runner.event.connect(events.append)
    runner.session_done.connect(results.append)

    sid = runner.start_session(
        prompt="say hi",
        system_prompt="you are a greeter",
        allowed_tools=["Read"],
        pane_roots=pane_roots,
    )

    _wait_until(lambda: len(results) == 1)
    assert sid
    assert [type(e).__name__ for e in events] == ["TextChunk", "TextChunk"]
    assert [e.text for e in events] == ["Hello, ", "world!"]
    assert results[0].session_id == sid
    assert results[0].status == "completed"
    assert results[0].text == "Hello, world!"
    assert results[0].tool_calls == 0
    assert results[0].cost_usd == 0.0001


def test_emits_tool_call_events(cli_present, pane_roots) -> None:
    _qapp()
    messages = [
        AssistantMessage(
            content=[
                TextBlock(text="reading…"),
                ToolUseBlock(id="tu_1", name="Read", input={"file_path": "x.txt"}),
            ],
            model="claude-sonnet-4-6",
        ),
        AssistantMessage(
            content=[
                ToolResultBlock(tool_use_id="tu_1", content="file body", is_error=False),
                TextBlock(text="done"),
            ],
            model="claude-sonnet-4-6",
        ),
        _result_message(),
    ]
    runner = AgentRunner(AiConfig(), query_fn=_make_query(messages))
    events: list[Any] = []
    results: list[AiResult] = []
    runner.event.connect(events.append)
    runner.session_done.connect(results.append)

    runner.start_session(
        prompt="read x", system_prompt="", allowed_tools=["Read"], pane_roots=pane_roots
    )

    _wait_until(lambda: len(results) == 1)
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["TextChunk", "ToolCallStart", "ToolCallEnd", "TextChunk"]
    assert isinstance(events[1], ToolCallStart)
    assert events[1].name == "Read"
    assert events[1].input == {"file_path": "x.txt"}
    assert isinstance(events[2], ToolCallEnd)
    assert events[2].ok is True
    assert results[0].tool_calls == 1
    assert results[0].text == "reading…done"


def test_propagates_query_exception_as_error_result(cli_present, pane_roots) -> None:
    _qapp()

    async def boom(*, prompt, options, transport=None):
        if False:
            yield None  # pragma: no cover  (make this an async generator)
        raise RuntimeError("transport blew up")

    runner = AgentRunner(AiConfig(), query_fn=boom)
    results: list[AiResult] = []
    events: list[Any] = []
    runner.event.connect(events.append)
    runner.session_done.connect(results.append)

    runner.start_session(
        prompt="x", system_prompt="", allowed_tools=[], pane_roots=pane_roots
    )

    _wait_until(lambda: len(results) == 1)
    assert results[0].status == "error"
    assert "transport blew up" in (results[0].error or "")
    # An AiError event was emitted before the result so a UI could surface it.
    assert any(type(e).__name__ == "AiError" for e in events)


def test_cancel_mid_stream_yields_cancelled_status(cli_present, pane_roots) -> None:
    _qapp()
    started = threading.Event()

    async def slow(*, prompt, options, transport=None):
        # First message arrives quickly so we know the worker entered the loop.
        yield AssistantMessage(
            content=[TextBlock(text="tick ")], model="claude-sonnet-4-6"
        )
        started.set()
        # Then a long pause that we'll cancel during.
        for _ in range(50):
            await asyncio.sleep(0.05)
            yield AssistantMessage(
                content=[TextBlock(text=".")], model="claude-sonnet-4-6"
            )
        yield _result_message()

    runner = AgentRunner(AiConfig(), query_fn=slow)
    results: list[AiResult] = []
    runner.session_done.connect(results.append)
    sid = runner.start_session(
        prompt="x", system_prompt="", allowed_tools=[], pane_roots=pane_roots
    )

    # Drive the event loop until the first message arrives, then cancel.
    _wait_until(started.is_set, timeout_ms=2000)
    runner.cancel(sid)
    _wait_until(lambda: len(results) == 1, timeout_ms=5000)

    assert results[0].status == "cancelled"


def test_raises_ai_unavailable_when_disabled(pane_roots) -> None:
    _qapp()
    runner = AgentRunner(AiConfig(enabled=False), query_fn=_make_query([]))
    with pytest.raises(AiUnavailable):
        runner.start_session(
            prompt="x", system_prompt="", allowed_tools=[], pane_roots=pane_roots
        )


def test_raises_ai_unavailable_when_cli_missing(monkeypatch, pane_roots) -> None:
    _qapp()
    from multipane_commander.services.ai import availability as av
    monkeypatch.setattr(av.shutil, "which", lambda _n: None)

    runner = AgentRunner(AiConfig(), query_fn=_make_query([]))
    with pytest.raises(AiUnavailable):
        runner.start_session(
            prompt="x", system_prompt="", allowed_tools=[], pane_roots=pane_roots
        )


# Ensure QCoreApplication lives long enough for queued cleanup signals.
@pytest.fixture(autouse=True)
def _drain_pending_events():
    yield
    app = QCoreApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
