"""Cross-test safety: quarantine the app data dir.

`platform.app_data_dir()` reads `APPDATA` on Windows and `XDG_CONFIG_HOME`
elsewhere. Tests that only set `APPDATA` fall through to the user's real
`~/Library/Application Support/MultiPaneCommander/` (macOS) or
`~/.config/MultiPaneCommander/` (Linux) and silently read/write production
state — observed today as flake when state from a prior pytest session
leaks into a later one.

The autouse fixture below points BOTH env vars at a fresh per-session
quarantine directory before any test body runs, so a test that forgets
to override either one still hits an empty disposable dir instead of
the user's data. Tests that need a specific path can still override
either env var locally with `monkeypatch.setenv` after this runs.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _quarantine_app_data_dir(tmp_path_factory, monkeypatch):
    quarantine = tmp_path_factory.mktemp("app_data_quarantine")
    monkeypatch.setenv("APPDATA", str(quarantine))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(quarantine))
    yield quarantine
