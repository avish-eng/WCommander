from __future__ import annotations

from multipane_commander.terminal.deep.shell_integration import (
    ShellIntegrationParser,
    looks_like_prompt,
)


def test_prompt_heuristic_accepts_common_prompts() -> None:
    assert looks_like_prompt("PS C:\\Users\\dev> ")
    assert looks_like_prompt("C:\\Users\\dev>")
    assert looks_like_prompt("\\\\server\\share>")
    assert looks_like_prompt("dev@host:~$ ")
    assert looks_like_prompt("~/project % ")
    assert looks_like_prompt("repo main ❯ ")
    assert looks_like_prompt("➜  src ")


def test_prompt_heuristic_rejects_continuations_and_repls() -> None:
    assert not looks_like_prompt("")
    assert not looks_like_prompt("   ")
    assert not looks_like_prompt("PS C:\\Users\\dev>> ")
    assert not looks_like_prompt("More?")
    assert not looks_like_prompt(">>> ")
    assert not looks_like_prompt("... ")


def test_parser_tracks_title_from_osc_0_and_2() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b]0;my title\x07")
    assert parser.title == "my title"

    parser.feed("\x1b]2;second;title\x1b\\")
    assert parser.title == "second;title"


def test_parser_tracks_posix_cwd_from_osc_7() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b]7;file://hostname/home/dev/my%20project\x07")

    assert parser.cwd == "/home/dev/my project"
    assert parser.integration_seen is True


def test_parser_tracks_windows_cwd_from_osc_7_and_9() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b]7;file:///C:/Users/dev/Project\x07")
    assert parser.cwd == "C:/Users/dev/Project"

    parser.feed("\x1b]9;9;C:\\Users\\dev\\Other\x07")
    assert parser.cwd == "C:\\Users\\dev\\Other"


def test_parser_tracks_prompt_marks_and_exit_status() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b]133;A\x07")
    assert parser.at_prompt is True
    assert parser.command_running is False

    parser.feed("\x1b]133;B\x07")
    assert parser.at_prompt is False
    assert parser.command_running is True

    parser.feed("\x1b]133;C\x07")
    parser.feed("\x1b]133;D;2\x07")
    assert parser.command_running is False
    assert parser.state.exit_code == 2


def test_parser_reads_command_from_osc_133_payload() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b]133;P;k=i;cmd=git status\x07")

    assert parser.state.last_command == "git status"
    assert parser.integration_seen is True


def test_parser_handles_sequences_split_across_chunks() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b]0;split")
    assert parser.title is None
    parser.feed(" title\x07")
    assert parser.title == "split title"

    parser.feed("\x1b]7;file:///home/dev/")
    parser.feed("deep\x07")
    assert parser.cwd == "/home/dev/deep"


def test_parser_handles_bel_and_st_terminators() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b]7;file:///home/a\x07")
    assert parser.cwd == "/home/a"
    parser.feed("\x1b]7;file:///home/b\x1b\\")
    assert parser.cwd == "/home/b"


def test_parser_ignores_csi_and_keeps_visible_text_clean() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b[31mhello\x1b[0m world")

    assert parser.visible_text() == "hello world"


def test_parser_keeps_visible_text_after_malformed_escape() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b[999;999;999Zafter")

    assert parser.visible_text() == "after"


def test_parser_detects_prompt_from_output_when_integration_is_absent() -> None:
    parser = ShellIntegrationParser()

    parser.feed("dev@host:~$ ")

    assert parser.at_prompt is True
    assert parser.integration_seen is False


def test_parser_note_input_marks_command_running() -> None:
    parser = ShellIntegrationParser()
    parser.feed("dev@host:~$ ")
    assert parser.at_prompt is True

    parser.note_input(b"ls -la\r")

    assert parser.at_prompt is False
    assert parser.command_running is True


def test_parser_note_input_ctrl_c_clears_running_state() -> None:
    parser = ShellIntegrationParser()
    parser.feed("dev@host:~$ ")
    parser.note_input(b"ls\r")
    assert parser.command_running is True

    parser.note_input(b"\x03")

    assert parser.command_running is False


def test_parser_rearms_prompt_after_command_completes_without_integration() -> None:
    parser = ShellIntegrationParser()
    parser.feed("C:\\Users\\dev> ")
    assert parser.at_prompt is True

    parser.note_input(b"echo hi\r")
    assert parser.at_prompt is False
    assert parser.command_running is True

    parser.feed("echo hi\r\nhi\r\nC:\\Users\\dev>")

    assert parser.at_prompt is True
    assert parser.command_running is False


def test_parser_does_not_rearm_on_command_output_continuation_lines() -> None:
    parser = ShellIntegrationParser()
    parser.feed("dev@host:~$ ")
    parser.note_input(b"cat file\r")

    parser.feed("first line\r\nMore?")

    assert parser.at_prompt is False
    assert parser.command_running is True


def test_parser_tracks_osc_9_4_progress() -> None:
    parser = ShellIntegrationParser()

    parser.feed("\x1b]9;4;1;42\x07")

    assert parser.state.progress == (1, 42)


def test_parser_reset_clears_state_and_pending() -> None:
    parser = ShellIntegrationParser()
    parser.feed("\x1b]0;pending title")

    parser.reset()

    assert parser.title is None
    assert parser.cwd is None
    assert parser.visible_text() == ""

    parser.feed(" title\x07")
    assert parser.title is None
