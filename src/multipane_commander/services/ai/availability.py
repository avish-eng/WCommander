from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AvailabilityStatus:
    available: bool
    cli_path: Path | None
    reason: str | None  # human-readable; None when available


def detect_claude_cli() -> AvailabilityStatus:
    """Cheap availability check.

    Looks up `claude` on PATH via shutil.which — does NOT execute the binary,
    so this is safe to call from app startup. We assume the user is logged
    in if the CLI exists; the SDK will surface a real auth error on first
    session if not.
    """
    found = shutil.which("claude")
    if not found:
        return AvailabilityStatus(
            available=False,
            cli_path=None,
            reason="Claude Code CLI not found on PATH. Install it from https://claude.com/code.",
        )
    return AvailabilityStatus(available=True, cli_path=Path(found), reason=None)
