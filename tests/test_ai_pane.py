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
from multipane_commander.ui.ai_pane import AiPane, _is_summarizable

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


# --- _is_summarizable unit tests (pure, no Qt needed) ---

def test_is_summarizable_text_file(tmp_path) -> None:
    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    assert _is_summarizable(f)


def test_is_summarizable_binary_rejected(tmp_path) -> None:
    f = tmp_path / "file.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")
    assert not _is_summarizable(f)


def test_is_summarizable_null_byte_rejected(tmp_path) -> None:
    f = tmp_path / "file.dat"
    f.write_bytes(b"text\x00more")
    assert not _is_summarizable(f)


def test_is_summarizable_extension_rejected(tmp_path) -> None:
    for ext in (".mp4", ".zip", ".pdf", ".svg"):
        f = tmp_path / f"file{ext}"
        f.write_bytes(b"data")
        assert not _is_summarizable(f), f"Expected {ext} to be rejected"


# --- Widget tests ---

def test_ai_pane_creates_without_crash() -> None:
    _qapp()
    pane = AiPane()
    assert pane is not None


def test_ai_pane_none_path_shows_idle_status(pane_roots) -> None:
    _qapp()
    runner = AgentRunner(AiConfig(), query_fn=_make_query([]))
    pane = AiPane()
    pane.set_runtime(runner, pane_roots)
    pane.set_path(None)
    assert "No AI summary" in pane._status.text()
    assert pane._session_id is None


def test_ai_pane_directory_shows_no_summary(tmp_path, pane_roots) -> None:
    _qapp()
    runner = AgentRunner(AiConfig(), query_fn=_make_query([]))
    pane = AiPane()
    pane.set_runtime(runner, pane_roots)
    pane.set_path(tmp_path)  # a directory
    assert "No AI summary" in pane._status.text()
    assert pane._session_id is None


def test_ai_pane_starts_session_for_text_file(cli_present, tmp_path, pane_roots) -> None:
    _qapp()
    txt = tmp_path / "hello.txt"
    txt.write_text("hello world")
    messages = [
        AssistantMessage(content=[TextBlock(text="This is a greeting file.")], model="m"),
        _result_msg(),
    ]
    runner = AgentRunner(AiConfig(), query_fn=_make_query(messages))
    pane = AiPane()
    pane.set_runtime(runner, pane_roots)
    pane.set_path(txt)

    _wait_until(lambda: pane._session_id is None and "Summary" in pane._status.text())
    assert "This is a greeting file." in pane._text_view.toPlainText()
    assert not pane._retry_btn.isHidden()
    assert pane._spinner.isHidden()


def test_ai_pane_skips_binary_file(tmp_path, pane_roots) -> None:
    _qapp()
    binary = tmp_path / "file.png"
    binary.write_bytes(b"\x89PNG\r\n")
    runner = AgentRunner(AiConfig(), query_fn=_make_query([]))
    pane = AiPane()
    pane.set_runtime(runner, pane_roots)
    pane.set_path(binary)
    assert pane._session_id is None
    assert "No AI summary" in pane._status.text()


def test_ai_pane_cancels_on_path_change(cli_present, tmp_path, pane_roots) -> None:
    _qapp()
    started = threading.Event()

    async def slow(*, prompt, options, transport=None):
        yield AssistantMessage(content=[TextBlock(text="tick")], model="m")
        started.set()
        for _ in range(20):
            await asyncio.sleep(0.05)
            yield AssistantMessage(content=[TextBlock(text=".")], model="m")
        yield _result_msg()

    txt1 = tmp_path / "a.txt"
    txt1.write_text("file a")
    txt2 = tmp_path / "b.txt"
    txt2.write_text("file b")

    runner = AgentRunner(AiConfig(), query_fn=slow)
    pane = AiPane()
    pane.set_runtime(runner, pane_roots)
    pane.set_path(txt1)

    _wait_until(started.is_set, timeout_ms=2000)
    old_sid = pane._session_id
    assert old_sid is not None

    pane.set_path(txt2)
    # New session should be different (or None if b.txt wasn't recognized quickly)
    assert pane._session_id != old_sid


def test_ai_pane_same_path_is_noop(cli_present, tmp_path, pane_roots) -> None:
    _qapp()
    call_count = [0]

    async def count_calls(*, prompt, options, transport=None):
        call_count[0] += 1
        yield AssistantMessage(content=[TextBlock(text="done")], model="m")
        yield _result_msg()

    txt = tmp_path / "f.txt"
    txt.write_text("content")

    runner = AgentRunner(AiConfig(), query_fn=count_calls)
    pane = AiPane()
    pane.set_runtime(runner, pane_roots)
    pane.set_path(txt)
    _wait_until(lambda: pane._session_id is None and "Summary" in pane._status.text())
    first_count = call_count[0]
    pane.set_path(txt)  # same path — no new session
    assert call_count[0] == first_count


@pytest.fixture(autouse=True)
def _drain_pending_events():
    yield
    app = QCoreApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
