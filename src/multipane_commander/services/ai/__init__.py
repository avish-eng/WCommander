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
from multipane_commander.services.ai.runner import (
    AgentRunner,
    AiUnavailable,
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
