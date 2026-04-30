from multipane_commander.terminal.ansi import TerminalBuffer


def test_terminal_buffer_handles_carriage_return_overwrite() -> None:
    buffer = TerminalBuffer()

    rendered = buffer.feed("hello\rbye")

    assert rendered == "byelo"


def test_terminal_buffer_handles_clear_line_from_cursor() -> None:
    buffer = TerminalBuffer()
    buffer.feed("hello world")
    buffer.feed("\r")
    buffer.feed("\x1b[6C")

    rendered = buffer.feed("\x1b[K")

    assert rendered == "hello "


def test_terminal_buffer_handles_clear_screen() -> None:
    buffer = TerminalBuffer()
    buffer.feed("first\nsecond")

    rendered = buffer.feed("\x1b[2Jafter")

    assert rendered == "after"


def test_terminal_buffer_handles_cursor_positioning() -> None:
    buffer = TerminalBuffer()
    buffer.feed("one\ntwo")

    rendered = buffer.feed("\x1b[1;1HZ")

    assert rendered == "Zne\ntwo"


def test_terminal_buffer_waits_for_complete_escape_sequence() -> None:
    buffer = TerminalBuffer()
    buffer.feed("abc")
    partial = buffer.feed("\x1b[2")
    complete = buffer.feed("Jdone")

    assert partial == "abc"
    assert complete == "done"


def test_terminal_buffer_wraps_at_configured_width() -> None:
    buffer = TerminalBuffer(cols=4)

    rendered = buffer.feed("abcdef")

    assert rendered == "abcd\nef"


def test_terminal_buffer_supports_save_and_restore_cursor() -> None:
    buffer = TerminalBuffer()

    rendered = buffer.feed("abc\x1b7ZZ\x1b8!")

    assert rendered == "abc!Z"


def test_terminal_buffer_clears_from_cursor_to_screen_end() -> None:
    buffer = TerminalBuffer()
    buffer.feed("hello\nworld")
    buffer.feed("\x1b[1;3H")

    rendered = buffer.feed("\x1b[J")

    assert rendered == "he"


def test_terminal_buffer_clears_from_screen_start_to_cursor() -> None:
    buffer = TerminalBuffer()
    buffer.feed("hello\nworld")
    buffer.feed("\x1b[2;3H")

    rendered = buffer.feed("\x1b[1J")

    assert rendered == "\n   ld"


def test_terminal_buffer_expands_tabs() -> None:
    buffer = TerminalBuffer(cols=16)

    rendered = buffer.feed("a\tb")

    assert rendered == "a       b"


def test_terminal_buffer_deletes_characters() -> None:
    buffer = TerminalBuffer()
    buffer.feed("abcdef")
    buffer.feed("\r")
    buffer.feed("\x1b[3C")

    rendered = buffer.feed("\x1b[2P")

    assert rendered == "abcf"


def test_terminal_buffer_inserts_blank_characters() -> None:
    buffer = TerminalBuffer()
    buffer.feed("abcd")
    buffer.feed("\r")
    buffer.feed("\x1b[3C")

    rendered = buffer.feed("\x1b[2@Z")

    assert rendered == "abcZ d"


def test_terminal_buffer_erases_characters_without_shifting() -> None:
    buffer = TerminalBuffer()
    buffer.feed("abcdef")
    buffer.feed("\r")
    buffer.feed("\x1b[3C")

    rendered = buffer.feed("\x1b[2X")

    assert rendered == "abc  f"


def test_terminal_buffer_inserts_and_deletes_lines() -> None:
    buffer = TerminalBuffer(rows=5)
    buffer.feed("one\ntwo\nthree")
    buffer.feed("\x1b[2;1H")
    inserted = buffer.feed("\x1b[LNEW")
    buffer.feed("\x1b[2;1H")
    deleted = buffer.feed("\x1b[M")

    assert inserted == "one\nNEW\ntwo\nthree"
    assert deleted == "one\ntwo\nthree"


def test_terminal_buffer_scrolls_when_exceeding_row_limit() -> None:
    buffer = TerminalBuffer(rows=3, scrollback_limit=3)

    rendered = buffer.feed("1\n2\n3\n4")

    assert rendered == "2\n3\n4"


def test_terminal_buffer_keeps_scrollback_beyond_viewport_height() -> None:
    buffer = TerminalBuffer(rows=3, scrollback_limit=10)

    rendered = buffer.feed("1\n2\n3\n4")

    assert rendered == "1\n2\n3\n4"


def test_terminal_buffer_restores_main_screen_after_alternate_screen() -> None:
    buffer = TerminalBuffer()
    buffer.feed("prompt\noutput")

    alternate = buffer.feed("\x1b[?1049hfull screen")
    restored = buffer.feed("\x1b[?1049l")

    assert alternate == "full screen"
    assert restored == "prompt\noutput"


def test_terminal_buffer_supports_vertical_position_absolute() -> None:
    buffer = TerminalBuffer()
    buffer.feed("one\ntwo\nthree")
    buffer.feed("\x1b[2d")

    rendered = buffer.feed("X")

    assert rendered == "one\ntwo  X\nthree"


def test_terminal_buffer_supports_scroll_up_and_down() -> None:
    buffer = TerminalBuffer(rows=4)
    buffer.feed("1\n2\n3\n4")

    scrolled_up = buffer.feed("\x1b[S")
    scrolled_down = buffer.feed("\x1b[T")

    assert scrolled_up == "2\n3\n4"
    assert scrolled_down == "\n2\n3\n4"
