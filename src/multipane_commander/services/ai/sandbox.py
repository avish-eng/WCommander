from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

CanUseToolFn = Callable[
    [str, dict[str, Any], ToolPermissionContext],
    Awaitable[PermissionResultAllow | PermissionResultDeny],
]

# Tool-input field names that carry filesystem paths the agent wants to touch.
# Anything not in this map is treated as a non-path tool — it's allowed only
# if the tool itself appears in the caller's allowed_tools list (the SDK
# already gates that). For path-bearing tools, every listed field is checked
# against the dual-pane sandbox.
_PATH_FIELDS_BY_TOOL: dict[str, tuple[str, ...]] = {
    "Read": ("file_path",),
    "Glob": ("path",),
    "Grep": ("path",),
}


@dataclass(frozen=True, slots=True)
class PaneRoots:
    """The agent's filesystem view: union of left + right pane roots.

    Anything outside both roots is denied at the tool-call boundary.
    """

    left: Path
    right: Path

    def contains(self, p: Path) -> bool:
        try:
            rp = p.expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            return False

        for root in (self.left, self.right):
            try:
                rr = root.expanduser().resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            if rp == rr or rp.is_relative_to(rr):
                return True
        return False


def make_can_use_tool(roots: PaneRoots) -> CanUseToolFn:
    """Build the SDK's `can_use_tool` callback, gated by the dual-pane sandbox.

    Returns a structured deny (not an exception) when a path escapes the
    sandbox so the agent can recover within the same turn instead of
    crashing the session.
    """

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        _context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        path_fields = _PATH_FIELDS_BY_TOOL.get(tool_name)
        if path_fields is None:
            return PermissionResultAllow()

        for field in path_fields:
            raw = tool_input.get(field)
            if raw is None:
                continue
            candidate = Path(str(raw))
            if not roots.contains(candidate):
                return PermissionResultDeny(
                    message=(
                        f"Path '{raw}' is outside the allowed pane roots "
                        f"({roots.left} | {roots.right})."
                    ),
                )

        return PermissionResultAllow()

    return can_use_tool
