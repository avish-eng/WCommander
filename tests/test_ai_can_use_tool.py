from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from multipane_commander.services.ai.sandbox import PaneRoots, make_can_use_tool


@pytest.fixture
def roots(tmp_path: Path) -> PaneRoots:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    return PaneRoots(left=left, right=right)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_allows_read_inside_left(roots: PaneRoots) -> None:
    callback = make_can_use_tool(roots)
    inside = roots.left / "file.txt"
    inside.write_text("x")
    result = _run(callback("Read", {"file_path": str(inside)}, ToolPermissionContext()))
    assert isinstance(result, PermissionResultAllow)


def test_allows_read_inside_right(roots: PaneRoots) -> None:
    callback = make_can_use_tool(roots)
    inside = roots.right / "file.txt"
    inside.write_text("x")
    result = _run(callback("Read", {"file_path": str(inside)}, ToolPermissionContext()))
    assert isinstance(result, PermissionResultAllow)


def test_denies_read_outside_both_roots(roots: PaneRoots, tmp_path: Path) -> None:
    callback = make_can_use_tool(roots)
    outside = tmp_path / "elsewhere" / "secret.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("nope")
    result = _run(callback("Read", {"file_path": str(outside)}, ToolPermissionContext()))
    assert isinstance(result, PermissionResultDeny)
    # Structured deny — does NOT raise. Agent can recover.
    assert "outside" in result.message.lower()


def test_denies_glob_outside(roots: PaneRoots) -> None:
    callback = make_can_use_tool(roots)
    result = _run(
        callback(
            "Glob",
            {"pattern": "*.py", "path": "/etc"},
            ToolPermissionContext(),
        )
    )
    assert isinstance(result, PermissionResultDeny)


def test_denies_grep_outside(roots: PaneRoots) -> None:
    callback = make_can_use_tool(roots)
    result = _run(
        callback(
            "Grep",
            {"pattern": "TODO", "path": "/etc"},
            ToolPermissionContext(),
        )
    )
    assert isinstance(result, PermissionResultDeny)


def test_allows_glob_without_path_argument(roots: PaneRoots) -> None:
    """Glob without explicit path uses the SDK's default cwd, which we set
    to a pane root in the runner. No path field => nothing to check here."""
    callback = make_can_use_tool(roots)
    result = _run(callback("Glob", {"pattern": "*.py"}, ToolPermissionContext()))
    assert isinstance(result, PermissionResultAllow)


def test_allows_unknown_tool_without_path_fields(roots: PaneRoots) -> None:
    """Tools we don't know about pass through. They still must be in
    allowed_tools to actually run — that's the SDK's job, not ours."""
    callback = make_can_use_tool(roots)
    result = _run(callback("WebSearch", {"query": "weather"}, ToolPermissionContext()))
    assert isinstance(result, PermissionResultAllow)
