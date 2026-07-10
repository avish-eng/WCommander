from __future__ import annotations

import ctypes
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PathSnapshot:
    process_entries: list[str]
    user_entries: list[str]
    machine_entries: list[str]


@dataclass(frozen=True, slots=True)
class WindowsPathSaveResult:
    user_entries: list[str]
    machine_entries: list[str]
    machine_written: bool
    reloaded_user_entries: list[str] | None = None
    reloaded_machine_entries: list[str] | None = None
    user_verified: bool = True
    machine_verified: bool = True


def split_path(value: str | None) -> list[str]:
    """Return non-empty PATH entries in display order."""
    if not value:
        return []
    return [entry.strip() for entry in value.split(os.pathsep) if entry.strip()]


def join_path(entries: list[str]) -> str:
    return os.pathsep.join(clean_entries(entries))


def clean_entries(entries: list[str]) -> list[str]:
    return [entry.strip() for entry in entries if entry.strip()]


def process_path_entries() -> list[str]:
    return split_path(os.environ.get(_path_env_key(), ""))


def set_process_path_entries(entries: list[str]) -> None:
    os.environ[_path_env_key()] = join_path(entries)


def path_entry_key(entry: str) -> str:
    return _path_key(entry)


def path_snapshot() -> PathSnapshot:
    return PathSnapshot(
        process_entries=process_path_entries(),
        user_entries=windows_user_path_entries(),
        machine_entries=windows_machine_path_entries(),
    )


def windows_user_path_entries() -> list[str]:
    return _read_windows_path_value(root="user")


def windows_machine_path_entries() -> list[str]:
    return _read_windows_path_value(root="machine")


def save_windows_user_path_from_effective_entries(
    entries: list[str],
    *,
    machine_entries: list[str] | None = None,
) -> list[str]:
    """Persist editable PATH entries to the current user's Windows PATH.

    Windows builds a process PATH from machine PATH plus user PATH. To avoid
    duplicating machine entries into the user value, entries matching the
    current machine PATH are filtered out before writing HKCU\\Environment\\Path.
    """
    if sys.platform != "win32":
        raise OSError("Saving PATH to Windows is only supported on Windows.")

    machine_keys = {_path_key(entry) for entry in (machine_entries or windows_machine_path_entries())}
    user_entries = [entry for entry in clean_entries(entries) if _path_key(entry) not in machine_keys]
    _write_windows_user_path(user_entries)
    set_process_path_entries(entries)
    _broadcast_environment_changed()
    return user_entries


def save_windows_path_entries(
    entries: list[str],
    sources: list[str],
    *,
    original_machine_entries: list[str],
    original_entries: list[str] | None = None,
    row_modified: list[bool] | None = None,
) -> WindowsPathSaveResult:
    """Persist source-aware PATH rows to Windows.

    Rows marked ``machine`` are written back to the machine PATH only when
    they changed. That requires elevation, so edits to user-only rows keep the
    admin-free path.
    """
    if sys.platform != "win32":
        raise OSError("Saving PATH to Windows is only supported on Windows.")
    if len(entries) != len(sources):
        raise ValueError("entries and sources must have matching lengths")
    if original_entries is not None and len(entries) != len(original_entries):
        raise ValueError("entries and original_entries must have matching lengths")
    if row_modified is not None and len(entries) != len(row_modified):
        raise ValueError("entries and row_modified must have matching lengths")

    logger.info(
        "PATH Save to Windows requested: entries=%s sources=%s original_entries=%s "
        "row_modified=%s original_machine_entries=%s",
        entries,
        sources,
        original_entries,
        row_modified,
        original_machine_entries,
    )

    rows: list[tuple[str, str, str, bool]] = []
    for index, (entry, source) in enumerate(zip(entries, sources, strict=False)):
        display_entry = entry.strip()
        if not display_entry:
            continue
        original_entry = ""
        if original_entries is not None:
            original_entry = original_entries[index].strip()
        modified = row_modified[index] if row_modified is not None else False
        saved_entry = (
            original_entry
            if original_entry and not modified and _path_key(display_entry) == _path_key(original_entry)
            else display_entry
        )
        rows.append((display_entry, saved_entry, source, modified))

    machine_entries = [
        saved_entry
        for _display_entry, saved_entry, source, _modified in rows
        if source == "machine"
    ]
    machine_keys = {_path_key(entry) for entry in machine_entries}
    user_entries = [
        saved_entry
        for _display_entry, saved_entry, source, _modified in rows
        if source != "machine" and _path_key(saved_entry) not in machine_keys
    ]

    logger.info(
        "PATH Save to Windows resolved rows: display_entries=%s user_entries=%s "
        "machine_entries=%s row_modified=%s",
        [display_entry for display_entry, _saved_entry, _source, _modified in rows],
        user_entries,
        machine_entries,
        [modified for _display_entry, _saved_entry, _source, modified in rows],
    )

    machine_written = False
    machine_changed = (
        _path_value_list(machine_entries) != _path_value_list(original_machine_entries)
        if original_entries is not None or row_modified is not None
        else _path_list_key(machine_entries) != _path_list_key(original_machine_entries)
    )
    if machine_changed:
        logger.info("PATH Save to Windows writing machine PATH: %s", machine_entries)
        _write_windows_machine_path(machine_entries)
        machine_written = True
    else:
        logger.info("PATH Save to Windows skipped machine PATH write: unchanged")

    logger.info("PATH Save to Windows writing user PATH: %s", user_entries)
    _write_windows_user_path(user_entries)
    set_process_path_entries([
        display_entry
        for display_entry, _saved_entry, _source, _modified in rows
    ])
    _broadcast_environment_changed()

    reloaded_user_entries = windows_user_path_entries()
    reloaded_machine_entries = windows_machine_path_entries()
    user_verified = _path_list_key(reloaded_user_entries) == _path_list_key(user_entries)
    machine_verified = _path_list_key(reloaded_machine_entries) == _path_list_key(machine_entries)
    if not user_verified or not machine_verified:
        logger.warning(
            "PATH Save to Windows verification mismatch: user_verified=%s "
            "machine_verified=%s expected_user=%s reloaded_user=%s expected_machine=%s "
            "reloaded_machine=%s",
            user_verified,
            machine_verified,
            user_entries,
            reloaded_user_entries,
            machine_entries,
            reloaded_machine_entries,
        )
    else:
        logger.info(
            "PATH Save to Windows verification ok: reloaded_user=%s reloaded_machine=%s",
            reloaded_user_entries,
            reloaded_machine_entries,
        )
    return WindowsPathSaveResult(
        user_entries=user_entries,
        machine_entries=machine_entries,
        machine_written=machine_written,
        reloaded_user_entries=reloaded_user_entries,
        reloaded_machine_entries=reloaded_machine_entries,
        user_verified=user_verified,
        machine_verified=machine_verified,
    )


def _read_windows_path_value(*, root: str) -> list[str]:
    if sys.platform != "win32":
        return []

    import winreg

    if root == "machine":
        hive = winreg.HKEY_LOCAL_MACHINE
        subkey = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    else:
        hive = winreg.HKEY_CURRENT_USER
        subkey = "Environment"

    try:
        with winreg.OpenKey(hive, subkey) as key:
            value, _value_type = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        return []
    except OSError:
        return []
    return split_path(str(value))


def _write_windows_user_path(entries: list[str]) -> None:
    import winreg

    value = join_path(entries)
    value_type = winreg.REG_EXPAND_SZ if "%" in value else winreg.REG_SZ
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, value_type, value)


def _write_windows_machine_path(entries: list[str]) -> None:
    import winreg

    value = join_path(entries)
    value_type = winreg.REG_EXPAND_SZ if "%" in value else winreg.REG_SZ
    subkey = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        subkey,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "Path", 0, value_type, value)


def _broadcast_environment_changed() -> None:
    if sys.platform != "win32":
        return

    hwnd_broadcast = 0xFFFF
    wm_settingchange = 0x001A
    smto_abortifhung = 0x0002
    timeout_ms = 5000
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(
        hwnd_broadcast,
        wm_settingchange,
        0,
        "Environment",
        smto_abortifhung,
        timeout_ms,
        ctypes.byref(result),
    )


def _path_env_key() -> str:
    for key in os.environ:
        if key.upper() == "PATH":
            return key
    return "PATH"


def _path_key(entry: str) -> str:
    expanded = os.path.expandvars(entry.strip())
    normalized = os.path.normcase(os.path.normpath(expanded))
    try:
        return os.path.normcase(str(Path(normalized)))
    except (OSError, RuntimeError):
        return normalized


def _path_list_key(entries: list[str]) -> list[str]:
    return [_path_key(entry) for entry in clean_entries(entries)]


def _path_value_list(entries: list[str]) -> list[str]:
    return [entry.strip() for entry in entries if entry.strip()]
