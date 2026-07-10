"""AI integration foundation.

Invisible plumbing for Claude Agent SDK features. No UI surface lives here —
features (#1 palette, #2 third pane, #3 F3 viewer) own their own widgets.
"""

from __future__ import annotations

from multipane_commander.services.ai.availability import (
    AvailabilityStatus,
    detect_claude_cli,
)
from multipane_commander.services.ai.events import (
    AiError,
    AiEvent,
    AiResult,
    TextChunk,
    ToolCallEnd,
    ToolCallStart,
)
try:
    from multipane_commander.services.ai.runner import (
        AgentRunner,
        AiUnavailable,
    )
except ModuleNotFoundError as exc:
    if exc.name != "claude_agent_sdk":
        raise

    class AiUnavailable(RuntimeError):
        """Raised when AI features can't run in the current environment."""

    class AgentRunner:  # type: ignore[no-redef]
        """Placeholder used when claude-agent-sdk is not installed."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AiUnavailable(
                "Claude Agent SDK is not installed. Install project dependencies "
                "with Python 3.12 or newer to enable AI features."
            )
from multipane_commander.services.ai.sandbox import (
    PaneRoots,
    make_can_use_tool,
)

__all__ = [
    "AgentRunner",
    "AiError",
    "AiEvent",
    "AiResult",
    "AiUnavailable",
    "AvailabilityStatus",
    "PaneRoots",
    "TextChunk",
    "ToolCallEnd",
    "ToolCallStart",
    "detect_claude_cli",
    "make_can_use_tool",
]
