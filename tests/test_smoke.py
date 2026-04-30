from multipane_commander.bootstrap import build_app_context


def test_bootstrap_builds_default_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    context = build_app_context()

    assert len(context.state.panes) == 2
    assert context.config.follow_active_pane_terminal is True
