"""Real-SDK integration tests for AgentRunner.

These tests call the actual Claude Code CLI and require it to be installed
and logged in.  They are skipped automatically when the CLI is absent.

Run explicitly with:
    pytest tests/test_ai_integration.py -v
"""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from multipane_commander.config.model import AiConfig
from multipane_commander.services.ai.events import AiResult
from multipane_commander.services.ai.runner import AgentRunner
from multipane_commander.services.ai.sandbox import PaneRoots

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.skipif(
    shutil.which("claude") is None,
    reason="Claude Code CLI not on PATH — skipping real-SDK tests",
)

_APP: QApplication | None = None
_TIMEOUT_MS = 60_000  # 60 s — generous for first-run CLI startup


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    _APP = QApplication([])
    return _APP


def _wait_until(predicate, timeout_ms: int = _TIMEOUT_MS) -> None:
    app = _qapp()
    deadline = threading.Event()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(deadline.set)
    timer.start(timeout_ms)
    while not predicate() and not deadline.is_set():
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


def test_real_session_returns_text(pane_roots: PaneRoots) -> None:
    """A minimal real session must complete with non-empty text."""
    _qapp()
    runner = AgentRunner(AiConfig())
    results: list[AiResult] = []
    runner.session_done.connect(results.append)

    runner.start_session(
        prompt="Reply with exactly the word: PONG",
        system_prompt="",
        allowed_tools=[],
        pane_roots=pane_roots,
    )

    _wait_until(lambda: len(results) == 1)
    assert results[0].status == "completed", f"unexpected status: {results[0]}"
    assert "PONG" in results[0].text


def test_real_session_read_tool(tmp_path: Path) -> None:
    """The agent can use the Read tool to read a file inside pane roots."""
    _qapp()
    left = tmp_path / "left"
    left.mkdir()
    right = tmp_path / "right"
    right.mkdir()
    target = left / "greeting.txt"
    target.write_text("HELLO_SENTINEL_VALUE", encoding="utf-8")

    roots = PaneRoots(left=left, right=right)
    runner = AgentRunner(AiConfig())
    results: list[AiResult] = []
    runner.session_done.connect(results.append)

    runner.start_session(
        prompt=f"Use Read to read {target}, then reply with only the exact file contents.",
        system_prompt="",
        allowed_tools=["Read"],
        pane_roots=roots,
    )

    _wait_until(lambda: len(results) == 1)
    assert results[0].status == "completed", f"unexpected status: {results[0]}"
    assert "HELLO_SENTINEL_VALUE" in results[0].text
    assert results[0].tool_calls >= 1


def test_real_session_cancel(pane_roots: PaneRoots) -> None:
    """Cancelling a live session produces status='cancelled'."""
    _qapp()
    first_event = threading.Event()
    runner = AgentRunner(AiConfig())
    results: list[AiResult] = []
    runner.session_done.connect(results.append)
    runner.event.connect(lambda _e: first_event.set())

    sid = runner.start_session(
        prompt="Count slowly from 1 to 100, one number per line.",
        system_prompt="",
        allowed_tools=[],
        pane_roots=pane_roots,
    )

    _wait_until(first_event.is_set, timeout_ms=30_000)
    runner.cancel(sid)
    _wait_until(lambda: len(results) == 1)
    assert results[0].status == "cancelled"


@pytest.fixture(autouse=True)
def _drain(request):
    yield
    app = QCoreApplication.instance()
    if app is not None:
        for _ in range(10):
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
