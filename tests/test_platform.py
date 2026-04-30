from __future__ import annotations

import sys
from pathlib import Path

from multipane_commander.platform import app_data_dir, build_cd_command, pick_shell, shell_line_ending


def test_app_data_dir_uses_xdg_on_linux(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert app_data_dir() == tmp_path / "MultiPaneCommander"


def test_app_data_dir_uses_library_support_on_macos(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    assert app_data_dir() == tmp_path / "Library" / "Application Support" / "MultiPaneCommander"


def test_pick_shell_prefers_posix_shell_when_pwsh_missing(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("SHELL", raising=False)

    def fake_which(name: str) -> str | None:
        return {"bash": "/bin/bash"}.get(name)

    monkeypatch.setattr("shutil.which", fake_which)

    shell = pick_shell()

    assert shell.program == "/bin/bash"
    assert shell.args == ["-i"]
    assert shell.kind == "posix"


def test_build_cd_command_supports_posix_paths() -> None:
    command = build_cd_command(Path("/tmp/it's-here"), "posix")
    assert command.startswith("cd -- '")
    assert command.endswith("it'\"'\"'s-here'")


def test_shell_line_ending_matches_shell_kind() -> None:
    assert shell_line_ending("posix") == "\n"
    assert shell_line_ending("cmd") == "\r\n"
