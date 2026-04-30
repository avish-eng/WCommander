from __future__ import annotations

import os
import shutil
import string
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShellSpec:
    program: str
    args: list[str]
    kind: str


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_macos() -> bool:
    return sys.platform == "darwin"


def app_data_dir(app_name: str = "MultiPaneCommander") -> Path:
    if is_windows():
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif is_macos():
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / "Library" / "Application Support"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / app_name


def root_section_label() -> str:
    return "This PC" if is_windows() else "Locations"


def root_paths() -> list[Path]:
    if is_windows():
        return [drive for drive in _windows_drive_paths() if drive.exists()]

    roots: list[Path] = [Path("/")]
    for mount_root in (Path("/Volumes"), Path("/mnt"), Path("/media")):
        if not mount_root.exists() or not mount_root.is_dir():
            continue
        try:
            mounted_children = sorted(
                [child for child in mount_root.iterdir() if child.exists()],
                key=lambda child: child.name.lower(),
            )
        except OSError:
            continue
        roots.extend(mounted_children)
    return _dedup_paths(path for path in roots if path.exists() and path.is_dir())


def same_filesystem(left: Path, right: Path) -> bool:
    try:
        return left.stat().st_dev == right.stat().st_dev
    except OSError:
        return _path_root_key(left) == _path_root_key(right)


def pick_shell() -> ShellSpec:
    pwsh = shutil.which("pwsh")
    if pwsh:
        return ShellSpec(program=pwsh, args=["-NoLogo"], kind="pwsh")

    if is_windows():
        return ShellSpec(program="cmd.exe", args=[], kind="cmd")

    shell_env = os.environ.get("SHELL")
    if shell_env:
        shell_path = Path(shell_env)
        if shell_path.exists():
            return ShellSpec(program=str(shell_path), args=["-i"], kind="posix")

    for candidate in ("bash", "zsh", "sh"):
        program = shutil.which(candidate)
        if program:
            return ShellSpec(program=program, args=["-i"], kind="posix")

    return ShellSpec(program="/bin/sh", args=["-i"], kind="posix")


def shell_line_ending(shell_kind: str) -> str:
    return "\n" if shell_kind == "posix" else "\r\n"


def build_cd_command(path: Path, shell_kind: str) -> str:
    if shell_kind == "pwsh":
        quoted = str(path).replace("'", "''")
        return f"Set-Location -LiteralPath '{quoted}'"
    if shell_kind == "cmd":
        quoted = str(path).replace('"', '""')
        return f'cd /d "{quoted}"'

    quoted = str(path).replace("'", "'\"'\"'")
    return f"cd -- '{quoted}'"


def _windows_drive_paths() -> list[Path]:
    return [Path(f"{letter}:\\") for letter in string.ascii_uppercase]


def _path_root_key(path: Path) -> str:
    normalized = path.expanduser()
    anchor = normalized.anchor or "/"
    return anchor.casefold() if is_windows() else anchor


def _dedup_paths(paths: list[Path] | tuple[Path, ...] | object) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if not isinstance(path, Path):
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique
