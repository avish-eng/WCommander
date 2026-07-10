from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from multipane_commander.services import env_path
from multipane_commander.services.env_path import PathSnapshot, WindowsPathSaveResult


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def test_split_and_join_path_entries() -> None:
    value = os.pathsep.join(["", " C:\\Tools ", "C:\\Python", ""])

    entries = env_path.split_path(value)

    assert entries == ["C:\\Tools", "C:\\Python"]
    assert env_path.join_path(entries) == os.pathsep.join(["C:\\Tools", "C:\\Python"])


def test_save_windows_user_path_filters_machine_entries(monkeypatch) -> None:
    written: list[list[str]] = []
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(env_path.sys, "platform", "win32")
    monkeypatch.setattr(env_path, "_write_windows_user_path", lambda entries: written.append(entries))
    monkeypatch.setattr(env_path, "_broadcast_environment_changed", lambda: None)

    saved = env_path.save_windows_user_path_from_effective_entries(
        ["C:\\Windows", "C:\\Tools", "C:\\Python"],
        machine_entries=["C:\\Windows"],
    )

    assert saved == ["C:\\Tools", "C:\\Python"]
    assert written == [["C:\\Tools", "C:\\Python"]]
    assert env_path.process_path_entries() == ["C:\\Windows", "C:\\Tools", "C:\\Python"]


def test_save_windows_path_entries_updates_machine_rows(monkeypatch) -> None:
    written_user: list[list[str]] = []
    written_machine: list[list[str]] = []
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setattr(env_path.sys, "platform", "win32")
    monkeypatch.setattr(env_path, "_write_windows_user_path", lambda entries: written_user.append(entries))
    monkeypatch.setattr(env_path, "_write_windows_machine_path", lambda entries: written_machine.append(entries))
    monkeypatch.setattr(env_path, "_broadcast_environment_changed", lambda: None)
    monkeypatch.setattr(env_path, "windows_user_path_entries", lambda: ["C:\\User"])
    monkeypatch.setattr(
        env_path,
        "windows_machine_path_entries",
        lambda: ["%SystemRoot%\\System32", "C:\\MachineNew"],
    )

    result = env_path.save_windows_path_entries(
        ["C:\\Windows\\System32", "C:\\MachineNew", "C:\\User"],
        ["machine", "machine", "user"],
        original_machine_entries=["%SystemRoot%\\System32", "C:\\MachineOld"],
        original_entries=["%SystemRoot%\\System32", "C:\\MachineOld", "C:\\User"],
    )

    assert result.machine_written is True
    assert result.user_verified is True
    assert result.machine_verified is True
    assert written_machine == [["%SystemRoot%\\System32", "C:\\MachineNew"]]
    assert written_user == [["C:\\User"]]
    assert env_path.process_path_entries() == [
        "C:\\Windows\\System32",
        "C:\\MachineNew",
        "C:\\User",
    ]


def test_save_windows_path_entries_writes_key_equivalent_modified_machine_row(
    monkeypatch,
) -> None:
    written_user: list[list[str]] = []
    written_machine: list[list[str]] = []
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setattr(env_path.sys, "platform", "win32")
    monkeypatch.setattr(env_path, "_write_windows_user_path", lambda entries: written_user.append(entries))
    monkeypatch.setattr(env_path, "_write_windows_machine_path", lambda entries: written_machine.append(entries))
    monkeypatch.setattr(env_path, "_broadcast_environment_changed", lambda: None)
    monkeypatch.setattr(env_path, "windows_user_path_entries", lambda: [])
    monkeypatch.setattr(env_path, "windows_machine_path_entries", lambda: ["C:\\Windows\\System32"])

    result = env_path.save_windows_path_entries(
        ["C:\\Windows\\System32"],
        ["machine"],
        original_machine_entries=["%SystemRoot%\\System32"],
        original_entries=["%SystemRoot%\\System32"],
        row_modified=[True],
    )

    assert result.machine_written is True
    assert result.machine_verified is True
    assert written_machine == [["C:\\Windows\\System32"]]
    assert written_user == [[]]


def test_path_dialog_edits_entries(monkeypatch) -> None:
    _qapp()
    from multipane_commander.ui import env_path_dialog
    from multipane_commander.ui.env_path_dialog import EnvPathDialog

    saved: list[list[str]] = []
    monkeypatch.setattr(
        env_path_dialog,
        "set_process_path_entries",
        lambda entries: saved.append(entries),
    )

    dialog = EnvPathDialog(
        parent=None,
        snapshot=PathSnapshot(
            process_entries=["C:\\One", "C:\\Two"],
            user_entries=[],
            machine_entries=[],
        ),
    )

    assert dialog.entries() == ["C:\\One", "C:\\Two"]

    dialog.table.selectRow(0)
    dialog._move_selected(1)
    assert dialog.entries() == ["C:\\Two", "C:\\One"]

    dialog._add_entry()
    added_editor = dialog.table.cellWidget(2, 0)
    assert isinstance(added_editor, QLineEdit)
    added_editor.setText("C:\\Three")
    dialog._save_process()

    assert saved == [["C:\\Two", "C:\\One", "C:\\Three"]]
    assert dialog.saved_to_process is True


def test_path_dialog_saves_source_metadata_to_windows(monkeypatch) -> None:
    _qapp()
    from multipane_commander.ui import env_path_dialog
    from multipane_commander.ui.env_path_dialog import EnvPathDialog

    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(env_path_dialog, "show_message", lambda **_kwargs: None)

    def fake_save(
        entries: list[str],
        sources: list[str],
        *,
        original_machine_entries: list[str],
        original_entries: list[str],
        row_modified: list[bool],
    ) -> WindowsPathSaveResult:
        captured["entries"] = entries
        captured["sources"] = sources
        captured["original_machine_entries"] = original_machine_entries
        captured["original_entries"] = original_entries
        captured["row_modified"] = row_modified
        return WindowsPathSaveResult(
            user_entries=["C:\\User"],
            machine_entries=["C:\\MachineNew"],
            machine_written=True,
        )

    monkeypatch.setattr(env_path_dialog, "save_windows_path_entries", fake_save)

    dialog = EnvPathDialog(
        parent=None,
        snapshot=PathSnapshot(
            process_entries=["C:\\Machine", "C:\\User"],
            user_entries=["C:\\User"],
            machine_entries=["C:\\Machine"],
        ),
    )
    assert dialog.sources() == ["machine", "user"]
    assert dialog.original_entries() == ["C:\\Machine", "C:\\User"]

    editor = dialog.table.cellWidget(0, 0)
    assert isinstance(editor, QLineEdit)
    editor.setText("C:\\MachineNew")
    dialog._save_windows()

    assert captured == {
        "entries": ["C:\\MachineNew", "C:\\User"],
        "sources": ["machine", "user"],
        "original_machine_entries": ["C:\\Machine"],
        "original_entries": ["C:\\Machine", "C:\\User"],
        "row_modified": [True, False],
    }
    assert dialog.saved_to_windows is True


def test_path_dialog_saves_in_place_entry_edits(monkeypatch) -> None:
    _qapp()
    from multipane_commander.ui import env_path_dialog
    from multipane_commander.ui.env_path_dialog import EnvPathDialog

    saved: list[list[str]] = []
    monkeypatch.setattr(
        env_path_dialog,
        "set_process_path_entries",
        lambda entries: saved.append(entries),
    )

    dialog = EnvPathDialog(
        parent=None,
        snapshot=PathSnapshot(
            process_entries=["C:\\Old", "C:\\Two"],
            user_entries=[],
            machine_entries=[],
        ),
    )
    editor = dialog.table.cellWidget(0, 0)
    assert isinstance(editor, QLineEdit)
    editor.setText("C:\\New")

    dialog._save_process()

    assert saved == [["C:\\New", "C:\\Two"]]


def test_path_dialog_save_persists_app_entries(monkeypatch) -> None:
    _qapp()
    from multipane_commander.ui import env_path_dialog
    from multipane_commander.ui.env_path_dialog import EnvPathDialog

    process_saved: list[list[str]] = []
    app_saved: list[tuple[list[str], list[str], list[str]]] = []
    monkeypatch.setattr(
        env_path_dialog,
        "set_process_path_entries",
        lambda entries: process_saved.append(entries),
    )

    dialog = EnvPathDialog(
        parent=None,
        snapshot=PathSnapshot(
            process_entries=["C:\\Old", "C:\\User"],
            user_entries=["C:\\User"],
            machine_entries=["C:\\Old"],
        ),
        save_app_entries=lambda entries, sources, originals: app_saved.append((entries, sources, originals)),
    )
    editor = dialog.table.cellWidget(0, 0)
    assert isinstance(editor, QLineEdit)
    editor.setText("C:\\New")

    dialog._save_process()

    assert process_saved == [["C:\\New", "C:\\User"]]
    assert app_saved == [
        (
            ["C:\\New", "C:\\User"],
            ["machine", "user"],
            ["C:\\Old", "C:\\User"],
        )
    ]
