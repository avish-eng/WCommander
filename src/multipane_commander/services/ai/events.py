from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class TextChunk:
    session_id: str
    text: str


@dataclass(slots=True)
class ToolCallStart:
    session_id: str
    tool_use_id: str
    name: str
    input: dict


@dataclass(slots=True)
class ToolCallEnd:
    session_id: str
    tool_use_id: str
    name: str
    ok: bool


@dataclass(slots=True)
class AiError:
    session_id: str
    message: str


AiEvent = TextChunk | ToolCallStart | ToolCallEnd | AiError


@dataclass(slots=True)
class AiResult:
    session_id: str
    status: Literal["completed", "cancelled", "error"]
    text: str
    tool_calls: int
    error: str | None = None
    usage: dict | None = None
    cost_usd: float | None = None
