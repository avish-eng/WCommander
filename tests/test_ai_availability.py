from __future__ import annotations

from pathlib import Path

from multipane_commander.services.ai import availability
from multipane_commander.services.ai.availability import (
    AvailabilityStatus,
    detect_claude_cli,
)


def test_detect_returns_unavailable_when_cli_missing(monkeypatch) -> None:
    monkeypatch.setattr(availability.shutil, "which", lambda _name: None)
    status = detect_claude_cli()
    assert status == AvailabilityStatus(
        available=False,
        cli_path=None,
        reason=status.reason,  # populated, exact text is informational
    )
    assert status.reason and "Claude Code CLI" in status.reason


def test_detect_returns_available_when_cli_found(monkeypatch, tmp_path) -> None:
    fake_path = tmp_path / "claude"
    fake_path.write_text("#!/bin/sh\n")
    monkeypatch.setattr(availability.shutil, "which", lambda _name: str(fake_path))
    status = detect_claude_cli()
    assert status.available is True
    assert status.cli_path == Path(fake_path)
    assert status.reason is None
