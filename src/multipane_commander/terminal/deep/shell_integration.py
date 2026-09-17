from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

_ESC = "\x1b"
_BEL = "\x07"
_ST = "\x1b\\"
_MAX_PENDING = 16_384
_MAX_TAIL = 8_192

_PS_PROMPT_RE = re.compile(r"^PS [^>]*>\s?$")
_CMD_PROMPT_RE = re.compile(r"^[A-Za-z]:\\[^>]*>\s?$")
_UNC_PROMPT_RE = re.compile(r"^\\\\[^>]*>\s?$")
_PROMPT_SUFFIX_RE = re.compile(r"[$#%❯➜]\s?$")
_PROMPT_PREFIX_RE = re.compile(r"^\s*[➜❯]\s")
_CONTINUATION_RE = re.compile(r"(?:>>|More\?)\s?$")
_PYTHON_REPL_RE = re.compile(r"(?:>>>|\.\.\.)\s?$")
_FILESYSTEM_CWD_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def _looks_like_gt_prompt(line: str) -> bool:
    trimmed = line.rstrip()
    if not trimmed.endswith(">") or len(trimmed) > 160:
        return False
    if "@" in trimmed:
        return True
    return trimmed[:1] in {"(", "[", "{"}


def looks_like_prompt(line: str) -> bool:
    """Heuristic: does this line look like an idle shell prompt?

    Deliberately conservative. It must not fire for continuation prompts
    (`>` / `>>` / `More?`) or the Python REPL, because the terminal only
    injects a directory change when the shell is idle. A trailing `>` is
    accepted only when the line carries another prompt signal (`user@host`,
    a leading bracket/paren, or a space after the `>`), which covers fish
    and most custom themes without matching arbitrary output.
    """
    cleaned = line.rstrip("\r\n")
    if not cleaned:
        return False
    if _CONTINUATION_RE.search(cleaned) or _PYTHON_REPL_RE.search(cleaned):
        return False
    if _PS_PROMPT_RE.match(cleaned) or _CMD_PROMPT_RE.match(cleaned) or _UNC_PROMPT_RE.match(cleaned):
        return True
    if _PROMPT_PREFIX_RE.match(cleaned):
        return True
    if _PROMPT_SUFFIX_RE.search(cleaned):
        return True
    return _looks_like_gt_prompt(cleaned)


@dataclass
class ShellIntegrationState:
    cwd: str | None = None
    title: str | None = None
    at_prompt: bool = False
    command_running: bool = False
    exit_code: int | None = None
    progress: tuple[int, int] | None = None
    last_command: str | None = None
    integration_seen: bool = False


class ShellIntegrationParser:
    """Incremental parser for the OSC sequences modern shells emit.

    Understands OSC 7 / OSC 9;9 (working directory), OSC 133 (prompt marks
    and exit status), OSC 0 / OSC 2 (title), OSC 9;4 (progress) and
    OSC 777 (notifications). Sequences that arrive split across reads are
    held back until complete, so a `cd` echoed in two chunks is still
    recognised. The parser never rewrites the byte stream; callers forward
    the original bytes to the renderer untouched.
    """

    def __init__(self) -> None:
        self.state = ShellIntegrationState()
        self._pending = ""
        self._tail = ""

    @property
    def cwd(self) -> str | None:
        return self.state.cwd

    @property
    def title(self) -> str | None:
        return self.state.title

    @property
    def at_prompt(self) -> bool:
        return self.state.at_prompt

    @property
    def command_running(self) -> bool:
        return self.state.command_running

    @property
    def integration_seen(self) -> bool:
        return self.state.integration_seen

    def visible_text(self) -> str:
        return self._tail

    def last_line(self) -> str:
        return self._tail.rsplit("\n", 1)[-1]

    def reset(self) -> None:
        self.state = ShellIntegrationState()
        self._pending = ""
        self._tail = ""

    def note_input(self, data: bytes) -> None:
        if not data:
            return
        text = data.decode("utf-8", errors="ignore")
        if "\x03" in text:
            self.state.at_prompt = False
            self.state.command_running = False
            return
        if "\r" in text or "\n" in text:
            self.state.at_prompt = False
            self.state.command_running = True
            self._tail = ""

    def feed(self, text: str) -> None:
        if not text and not self._pending:
            return
        stream = self._pending + text
        self._pending = ""
        visible: list[str] = []
        index = 0
        length = len(stream)
        while index < length:
            char = stream[index]
            if char == _ESC:
                if index + 1 >= length:
                    self._pending = stream[index:]
                    break
                nxt = stream[index + 1]
                if nxt == "]":
                    consumed = self._consume_osc(stream, index)
                    if consumed == 0:
                        self._pending = stream[index:]
                        break
                    index += consumed
                    continue
                if nxt == "[":
                    consumed = self._consume_csi(stream, index)
                    if consumed == 0:
                        self._pending = stream[index:]
                        break
                    index += consumed
                    continue
                if nxt in "P^_X":
                    consumed = self._consume_string_control(stream, index)
                    if consumed == 0:
                        self._pending = stream[index:]
                        break
                    index += consumed
                    continue
                index += 2
                continue
            if char in "\r\n":
                visible.append("\n")
                index += 1
                continue
            if char >= " ":
                visible.append(char)
            index += 1

        if visible:
            self._tail = (self._tail + "".join(visible))[-_MAX_TAIL:]
            self._update_heuristic()

    def _update_heuristic(self) -> None:
        if self.state.at_prompt:
            return
        if looks_like_prompt(self.last_line()):
            self.state.at_prompt = True
            self.state.command_running = False
            # Standard Windows prompts report the directory even without OSC.
            # Only filesystem locations are accepted; PowerShell drives such
            # as HKLM: are not directories the pane can follow.
            line = self.last_line().strip()
            candidate: str | None = None
            if _PS_PROMPT_RE.match(line):
                candidate = line[3:-1]
            elif _CMD_PROMPT_RE.match(line) or _UNC_PROMPT_RE.match(line):
                candidate = line[:-1]
            if candidate and _FILESYSTEM_CWD_RE.match(candidate):
                self.state.cwd = candidate

    def _consume_osc(self, stream: str, start: int) -> int:
        index = start + 2
        length = len(stream)
        while index < length:
            char = stream[index]
            if char == _BEL:
                self._handle_osc(stream[start + 2 : index])
                return index + 1 - start
            if char == _ESC:
                if index + 1 >= length:
                    return 0
                if stream[index + 1] == "\\":
                    self._handle_osc(stream[start + 2 : index])
                    return index + 2 - start
            index += 1
        if length - start > _MAX_PENDING:
            return length - start
        return 0

    def _consume_csi(self, stream: str, start: int) -> int:
        index = start + 2
        length = len(stream)
        while index < length:
            char = stream[index]
            if "@" <= char <= "~":
                return index + 1 - start
            index += 1
        if length - start > _MAX_PENDING:
            return length - start
        return 0

    def _consume_string_control(self, stream: str, start: int) -> int:
        index = start + 2
        length = len(stream)
        while index < length:
            char = stream[index]
            if char == _BEL:
                return index + 1 - start
            if char == _ESC and index + 1 < length and stream[index + 1] == "\\":
                return index + 2 - start
            index += 1
        if length - start > _MAX_PENDING:
            return length - start
        return 0

    def _handle_osc(self, payload: str) -> None:
        if not payload:
            return
        code, _, rest = payload.partition(";")
        if code in {"0", "2"}:
            title = rest.strip()
            if title:
                self.state.title = title
            return
        if code == "7":
            self._handle_cwd_uri(rest)
            return
        if code == "9":
            self._handle_osc_9(rest)
            return
        if code == "133":
            self._handle_osc_133(rest)
            return
        if code == "777":
            self._handle_osc_777(rest)

    def _handle_cwd_uri(self, value: str) -> None:
        if not value:
            return
        parsed = urlparse(value)
        path = unquote(parsed.path or "")
        if not path:
            return
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        self.state.cwd = path
        self.state.integration_seen = True

    def _handle_osc_9(self, rest: str) -> None:
        parts = rest.split(";")
        if not parts:
            return
        if parts[0] == "9" and len(parts) >= 2:
            cwd = ";".join(parts[1:])
            if cwd:
                self.state.cwd = cwd
                self.state.integration_seen = True
            return
        if parts[0] == "4" and len(parts) >= 3:
            try:
                state = int(parts[1])
                progress = int(parts[2])
            except ValueError:
                return
            self.state.progress = (state, progress)

    def _handle_osc_133(self, rest: str) -> None:
        parts = rest.split(";")
        if not parts:
            return
        kind = parts[0]
        if kind == "A":
            self.state.at_prompt = True
            self.state.command_running = False
            self.state.integration_seen = True
        elif kind == "B":
            # OSC 133 B ends the prompt; input follows, not command execution.
            self.state.at_prompt = True
            self.state.command_running = False
            self.state.integration_seen = True
        elif kind == "C":
            self.state.at_prompt = False
            self.state.command_running = True
            self.state.integration_seen = True
        elif kind == "D":
            self.state.command_running = False
            if len(parts) >= 2 and parts[1]:
                try:
                    self.state.exit_code = int(parts[1])
                except ValueError:
                    pass
        elif kind == "P":
            for part in parts[1:]:
                if part.startswith("cmd="):
                    self.state.last_command = part[4:]
                    self.state.integration_seen = True

    def _handle_osc_777(self, rest: str) -> None:
        parts = rest.split(";")
        if len(parts) >= 2 and parts[0] == "notify":
            self.state.integration_seen = True
