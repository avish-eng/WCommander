from test_deep_integration import _make_window, _patch_terminals
from multipane_commander.ui.command_bar import CommandBar


def test_busy_terminal_keeps_command_bar_input_until_successful_retry(tmp_path, monkeypatch):
    sessions = _patch_terminals(monkeypatch)
    window = _make_window(tmp_path)
    try:
        window.command_bar = CommandBar(window)
        window._bind_command_bar()
        bar = window.command_bar
        session = sessions[0]
        session.at_prompt = False
        bar._input.setText("echo keep this command")
        bar._escalate_to_terminal()
        assert bar._input.text() == "echo keep this command"
        assert not bar._history
        assert not session.commands

        session.at_prompt = True
        bar._escalate_to_terminal()
        assert bar._input.text() == ""
        assert bar._history == ["echo keep this command"]
        assert session.commands == [("echo keep this command", tmp_path / "left", True)]
    finally:
        window.close()
