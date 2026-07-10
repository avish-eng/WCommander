from multipane_commander import app as app_mod
from multipane_commander.bootstrap import build_app_context


def test_bootstrap_builds_default_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    context = build_app_context()

    assert len(context.state.panes) == 2
    assert context.config.follow_active_pane_terminal is True


def test_configure_native_runtime_uses_windows_archiveint(tmp_path, monkeypatch) -> None:
    system32 = tmp_path / "System32"
    system32.mkdir()
    archiveint = system32 / "archiveint.dll"
    archiveint.write_bytes(b"")

    monkeypatch.delenv("LIBARCHIVE", raising=False)
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setattr(app_mod.os, "name", "nt")

    app_mod.configure_native_runtime()

    assert app_mod.os.environ["LIBARCHIVE"] == str(archiveint)
