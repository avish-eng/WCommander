from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from multipane_commander.config.model import AiConfig
from multipane_commander.services.ai.runner import AgentRunner
from multipane_commander.services.ai.sandbox import PaneRoots
from multipane_commander.ui.ai_chat import AiChatWidget, _build_history_prompt

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
    async def fake(*, prompt, options, transport=None):
        for msg in messages:
            await asyncio.sleep(0)
            yield msg

    return fake


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


# --- Pure unit tests for _build_history_prompt ---

def test_build_history_prompt_empty_returns_current() -> None:
    assert _build_history_prompt([], "hello") == "hello"


def test_build_history_prompt_includes_prior_turns() -> None:
    history = [("q1", "a1"), ("q2", "a2")]
    result = _build_history_prompt(history, "q3")
    assert "Previous conversation:" in result
    assert "User: q1" in result
    assert "Assistant: a1" in result
    assert "User: q2" in result
    assert "Assistant: a2" in result
    assert "Current question: q3" in result


def test_build_history_prompt_single_turn() -> None:
    result = _build_history_prompt([("first", "reply")], "second")
    assert "first" in result
    assert "reply" in result
    assert "second" in result


# --- Widget tests ---

def test_chat_creates_without_crash(pane_roots) -> None:
    _qapp()
    runner = AgentRunner(AiConfig(), query_fn=_make_query([]))
    widget = AiChatWidget()
    widget.set_runtime(runner, pane_roots)
    assert widget is not None


def test_chat_send_adds_history_entry(cli_present, pane_roots) -> None:
    _qapp()
    messages = [
        AssistantMessage(content=[TextBlock(text="Hello from Claude")], model="m"),
        _result_msg(),
    ]
    runner = AgentRunner(AiConfig(), query_fn=_make_query(messages))
    widget = AiChatWidget()
    widget.set_runtime(runner, pane_roots)
    widget.show()

    widget._input.setPlainText("test message")
    widget._send()
    _wait_until(lambda: len(widget._history) == 1)

    assert widget._history[0][0] == "test message"
    assert "Hello from Claude" in widget._history[0][1]
    assert "Turn 1" in widget._status.text()
    assert widget._session_id is None


def test_chat_history_prepended_in_second_turn(cli_present, pane_roots) -> None:
    _qapp()
    sent_prompts: list[str] = []

    async def record(*, prompt, options, transport=None):
        sent_prompts.append(prompt)
        yield AssistantMessage(content=[TextBlock(text="reply")], model="m")
        yield _result_msg()

    runner = AgentRunner(AiConfig(), query_fn=record)
    widget = AiChatWidget()
    widget.set_runtime(runner, pane_roots)
    widget.show()

    widget._input.setPlainText("first question")
    widget._send()
    _wait_until(lambda: len(widget._history) == 1)

    widget._input.setPlainText("second question")
    widget._send()
    _wait_until(lambda: len(widget._history) == 2)

    # First prompt goes straight through
    assert sent_prompts[0] == "first question"
    # Second prompt includes conversation history
    assert "Previous conversation:" in sent_prompts[1]
    assert "first question" in sent_prompts[1]
    assert "Current question: second question" in sent_prompts[1]


def test_chat_clear_resets_state(cli_present, pane_roots) -> None:
    _qapp()
    messages = [
        AssistantMessage(content=[TextBlock(text="reply")], model="m"),
        _result_msg(),
    ]
    runner = AgentRunner(AiConfig(), query_fn=_make_query(messages))
    widget = AiChatWidget()
    widget.set_runtime(runner, pane_roots)
    widget.show()

    widget._input.setPlainText("msg")
    widget._send()
    _wait_until(lambda: len(widget._history) == 1)

    widget._clear()
    assert widget._history == []
    assert widget._session_id is None
    assert widget._send_btn.isEnabled()
    assert not widget._spinner.isVisible()


def test_chat_no_runtime_shows_error(pane_roots) -> None:
    _qapp()
    widget = AiChatWidget()
    # No runtime set
    widget._input.setPlainText("hello")
    widget._send()
    assert "unavailable" in widget._status.text()


def test_chat_update_pane_roots(pane_roots, tmp_path) -> None:
    _qapp()
    runner = AgentRunner(AiConfig(), query_fn=_make_query([]))
    widget = AiChatWidget()
    widget.set_runtime(runner, pane_roots)
    new_left = tmp_path / "nl"
    new_left.mkdir()
    new_right = tmp_path / "nr"
    new_right.mkdir()
    new_roots = PaneRoots(left=new_left, right=new_right)
    widget.update_pane_roots(new_roots)
    assert widget._pane_roots is new_roots


@pytest.fixture(autouse=True)
def _drain_pending_events():
    yield
    app = QCoreApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
