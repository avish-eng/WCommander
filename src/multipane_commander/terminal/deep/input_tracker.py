from __future__ import annotations

import codecs


def _skip_escape_sequence(text: str, start: int) -> int:
    index = start + 1
    if index >= len(text):
        return index
    if text[index] == "[":
        index += 1
        while index < len(text):
            if "@" <= text[index] <= "~":
                return index + 1
            index += 1
        return index
    if text[index] == "]":
        index += 1
        while index < len(text):
            if text[index] == "\a":
                return index + 1
            if text[index : index + 2] == "\x1b\\":
                return index + 2
            index += 1
        return index
    return min(len(text), index + 1)


class InputDraftTracker:
    """Track the command line a user types, without parsing terminal output.

    Feeds on the raw bytes sent from the renderer, so backspace, Ctrl+U and
    Ctrl+W edit the draft exactly the way the shell sees them. UTF-8
    sequences split across reads are decoded incrementally. Escape sequences
    (arrow keys, Home/End) are skipped, which keeps cursor movement from
    corrupting the draft.
    """

    def __init__(self, draft: str = "") -> None:
        self._draft = draft
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")

    @property
    def draft(self) -> str:
        return self._draft

    def reset(self) -> None:
        self._draft = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def set_draft(self, draft: str) -> None:
        self._draft = draft

    def feed(self, data: bytes) -> list[str]:
        submitted: list[str] = []
        text = self._decoder.decode(data)
        index = 0
        while index < len(text):
            char = text[index]
            if char == "\x1b":
                index = _skip_escape_sequence(text, index)
                continue
            if char in "\r\n":
                command = self._draft.strip()
                if command:
                    submitted.append(command)
                self._draft = ""
            elif char in "\x08\x7f":
                self._draft = self._draft[:-1]
            elif char == "\x15":
                self._draft = ""
            elif char == "\x17":
                self._draft = self._draft.rstrip().rsplit(" ", 1)[0] if self._draft.strip() else ""
            elif char == "\x0b":
                self._draft = self._draft.rstrip()
            elif char in "\x03\x04\x11\x1a":
                self._draft = ""
            elif char >= " ":
                self._draft += char
            index += 1
        return submitted


def update_draft_from_input(draft: str, data: bytes) -> tuple[str, list[str]]:
    tracker = InputDraftTracker(draft)
    submitted = tracker.feed(data)
    return tracker.draft, submitted
