from __future__ import annotations

from multipane_commander.terminal.deep.input_tracker import (
    InputDraftTracker,
    update_draft_from_input,
)


def test_tracker_tracks_typed_draft_and_submits() -> None:
    tracker = InputDraftTracker()

    submitted = tracker.feed(b"git sta")

    assert submitted == []
    assert tracker.draft == "git sta"

    submitted = tracker.feed(b"tus\r")

    assert submitted == ["git status"]
    assert tracker.draft == ""


def test_tracker_edits_draft_with_backspace_and_ctrl_keys() -> None:
    tracker = InputDraftTracker()

    tracker.feed(b"echo helXo\x7f\x7f")
    assert tracker.draft == "echo hel"

    tracker.feed(b"lo")
    assert tracker.draft == "echo hello"

    tracker.feed(b"\x15")
    assert tracker.draft == ""

    tracker.feed(b"one two\x17")
    assert tracker.draft == "one"

    tracker.feed(b" three\x0b")
    assert tracker.draft == "one three"


def test_tracker_skips_escape_sequences() -> None:
    tracker = InputDraftTracker()

    tracker.feed(b"abc\x1b[D\x1b[Dx")

    assert tracker.draft == "abcx"


def test_tracker_ignores_control_sequences_and_clears_on_interrupt() -> None:
    tracker = InputDraftTracker()
    tracker.feed(b"partial")
    assert tracker.draft == "partial"

    tracker.feed(b"\x03")
    assert tracker.draft == ""


def test_tracker_decodes_utf8_split_across_reads() -> None:
    tracker = InputDraftTracker()
    encoded = "héllo".encode()

    tracker.feed(encoded[:2])
    tracker.feed(encoded[2:])

    assert tracker.draft == "héllo"


def test_tracker_collects_multiple_submitted_commands() -> None:
    tracker = InputDraftTracker()

    submitted = tracker.feed(b"first\rsecond\n")

    assert submitted == ["first", "second"]
    assert tracker.draft == ""


def test_update_draft_from_input_wrapper_is_stateless() -> None:
    draft, submitted = update_draft_from_input("", b"echo worlx\x7fd\x1b[A\r")

    assert draft == ""
    assert submitted == ["echo world"]


def test_tracker_reset_clears_draft() -> None:
    tracker = InputDraftTracker("partial")

    tracker.reset()

    assert tracker.draft == ""
    tracker.feed(b"next")
    assert tracker.draft == "next"
