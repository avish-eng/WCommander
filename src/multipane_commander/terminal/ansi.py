from __future__ import annotations

import re
from dataclasses import dataclass, field


_CSI_RE = re.compile(r"\x1b\[([0-9;?]*)([@-~])")


@dataclass
class TerminalBuffer:
    lines: list[list[str]] = field(default_factory=lambda: [[]])
    cursor_row: int = 0
    cursor_col: int = 0
    cols: int = 80
    rows: int = 24
    scrollback_limit: int = 2000
    saved_cursor_row: int = 0
    saved_cursor_col: int = 0
    _pending: str = ""
    _main_lines: list[list[str]] | None = None
    _main_cursor_row: int = 0
    _main_cursor_col: int = 0
    _main_saved_cursor_row: int = 0
    _main_saved_cursor_col: int = 0

    def feed(self, text: str) -> str:
        if not text and not self._pending:
            return self.render()

        stream = self._pending + text
        self._pending = ""
        index = 0
        length = len(stream)

        while index < length:
            char = stream[index]
            if char == "\x1b":
                consumed = self._consume_escape(stream[index:])
                if consumed == 0:
                    self._pending = stream[index:]
                    break
                index += consumed
                continue
            if char == "\r":
                self.cursor_col = 0
            elif char == "\n":
                self.cursor_row += 1
                self.cursor_col = 0
                self._ensure_row(self.cursor_row)
            elif char == "\t":
                next_tab_stop = min(self.cols, ((self.cursor_col // 8) + 1) * 8)
                while self.cursor_col < next_tab_stop:
                    self._put_char(" ")
            elif char == "\b":
                self.cursor_col = max(0, self.cursor_col - 1)
            elif char >= " ":
                self._put_char(char)
            index += 1

        return self.render()

    def render(self) -> str:
        rendered_lines = ["".join(line) for line in self.lines]
        while rendered_lines and rendered_lines[-1] == "":
            rendered_lines.pop()
        return "\n".join(rendered_lines)

    def clear(self) -> None:
        self.lines = [[]]
        self.cursor_row = 0
        self.cursor_col = 0
        self.saved_cursor_row = 0
        self.saved_cursor_col = 0
        self._pending = ""

    def set_size(self, cols: int, rows: int) -> None:
        self.cols = max(1, cols)
        self.rows = max(1, rows)

    def _consume_escape(self, text: str) -> int:
        if len(text) == 1:
            return 0
        if text.startswith("\x1b]"):
            terminator = self._find_osc_terminator(text)
            return terminator if terminator > 0 else 0
        if text.startswith("\x1b7"):
            self.saved_cursor_row = self.cursor_row
            self.saved_cursor_col = self.cursor_col
            return 2
        if text.startswith("\x1b8"):
            self.cursor_row = self.saved_cursor_row
            self.cursor_col = self.saved_cursor_col
            self._ensure_row(self.cursor_row)
            return 2

        match = _CSI_RE.match(text)
        if match is None:
            if text.startswith("\x1b["):
                return 0
            return 1

        params_text, command = match.groups()
        private = params_text.startswith("?")
        params = self._parse_params(params_text)
        self._apply_csi(command, params, private=private)
        return match.end()

    def _find_osc_terminator(self, text: str) -> int:
        bell = text.find("\x07", 2)
        st = text.find("\x1b\\", 2)
        if bell == -1 and st == -1:
            return 0
        if bell != -1 and (st == -1 or bell < st):
            return bell + 1
        return st + 2

    def _parse_params(self, params_text: str) -> list[int]:
        if not params_text:
            return []
        cleaned = params_text.lstrip("?")
        if not cleaned:
            return []
        params: list[int] = []
        for part in cleaned.split(";"):
            if not part:
                params.append(0)
                continue
            try:
                params.append(int(part))
            except ValueError:
                params.append(0)
        return params

    def _apply_csi(self, command: str, params: list[int], *, private: bool = False) -> None:
        if command == "A":
            self.cursor_row = max(0, self.cursor_row - self._param(params, 1))
        elif command == "B":
            self._move_rows(self._param(params, 1))
        elif command == "C":
            self.cursor_col += self._param(params, 1)
        elif command == "D":
            self.cursor_col = max(0, self.cursor_col - self._param(params, 1))
        elif command == "E":
            self._move_rows(self._param(params, 1))
            self.cursor_col = 0
        elif command == "F":
            self.cursor_row = max(0, self.cursor_row - self._param(params, 1))
            self.cursor_col = 0
        elif command == "G":
            self.cursor_col = max(1, self._param(params, 1)) - 1
        elif command == "d":
            self.cursor_row = max(1, self._param(params, 1)) - 1
            self._ensure_row(self.cursor_row)
        elif command == "@":
            self._insert_chars(self._param(params, 1))
        elif command == "P":
            self._delete_chars(self._param(params, 1))
        elif command == "X":
            self._erase_chars(self._param(params, 1))
        elif command == "L":
            self._insert_lines(self._param(params, 1))
        elif command == "M":
            self._delete_lines(self._param(params, 1))
        elif command == "S":
            self._scroll_up(self._param(params, 1))
        elif command == "T":
            self._scroll_down(self._param(params, 1))
        elif command in {"H", "f"}:
            row = max(1, self._param(params[:1], 1)) - 1
            col = max(1, self._param(params[1:2], 1)) - 1
            self.cursor_row = row
            self.cursor_col = col
            self._ensure_row(self.cursor_row)
        elif command == "J":
            mode = self._param(params, 0)
            if mode == 2:
                self.clear()
            elif mode == 0:
                self._clear_to_screen_end()
            elif mode == 1:
                self._clear_to_screen_start()
        elif command == "K":
            mode = self._param(params, 0)
            self._clear_line(mode)
        elif command == "m":
            return
        elif command == "h":
            self._apply_mode(params, enabled=True, private=private)
        elif command == "l":
            self._apply_mode(params, enabled=False, private=private)
        elif command == "s":
            self.saved_cursor_row = self.cursor_row
            self.saved_cursor_col = self.cursor_col
        elif command == "u":
            self.cursor_row = self.saved_cursor_row
            self.cursor_col = self.saved_cursor_col
            self._ensure_row(self.cursor_row)

    def _clear_line(self, mode: int) -> None:
        self._ensure_row(self.cursor_row)
        line = self.lines[self.cursor_row]
        if mode == 2:
            self.lines[self.cursor_row] = []
            self.cursor_col = 0
            return
        if mode == 1:
            upto = min(self.cursor_col + 1, len(line))
            for index in range(upto):
                line[index] = " "
            return
        if self.cursor_col < len(line):
            del line[self.cursor_col :]

    def _clear_to_screen_end(self) -> None:
        self._clear_line(0)
        for row in range(self.cursor_row + 1, len(self.lines)):
            self.lines[row] = []

    def _clear_to_screen_start(self) -> None:
        self._clear_line(1)
        for row in range(0, self.cursor_row):
            self.lines[row] = []

    def _insert_chars(self, count: int) -> None:
        self._ensure_row(self.cursor_row)
        line = self.lines[self.cursor_row]
        while len(line) < self.cursor_col:
            line.append(" ")
        for _ in range(max(1, count)):
            line.insert(self.cursor_col, " ")
        if len(line) > self.cols:
            del line[self.cols :]

    def _delete_chars(self, count: int) -> None:
        self._ensure_row(self.cursor_row)
        line = self.lines[self.cursor_row]
        if self.cursor_col >= len(line):
            return
        del line[self.cursor_col : self.cursor_col + max(1, count)]

    def _erase_chars(self, count: int) -> None:
        self._ensure_row(self.cursor_row)
        line = self.lines[self.cursor_row]
        while len(line) < self.cursor_col:
            line.append(" ")
        for index in range(self.cursor_col, min(len(line), self.cursor_col + max(1, count))):
            line[index] = " "

    def _insert_lines(self, count: int) -> None:
        self._ensure_row(self.cursor_row)
        for _ in range(max(1, count)):
            self.lines.insert(self.cursor_row, [])
        self._trim_to_limit()

    def _delete_lines(self, count: int) -> None:
        self._ensure_row(self.cursor_row)
        for _ in range(max(1, count)):
            if self.cursor_row < len(self.lines):
                del self.lines[self.cursor_row]
            self.lines.append([])
        self._trim_to_limit()

    def _scroll_up(self, count: int) -> None:
        steps = max(1, count)
        for _ in range(steps):
            if self.lines:
                del self.lines[0]
            self.lines.append([])
        self.cursor_row = max(0, self.cursor_row - steps)
        self._ensure_row(self.cursor_row)

    def _scroll_down(self, count: int) -> None:
        steps = max(1, count)
        for _ in range(steps):
            self.lines.insert(0, [])
        self._trim_to_limit()
        self.cursor_row = min(self.rows - 1, self.cursor_row + steps)
        self._ensure_row(self.cursor_row)

    def _apply_mode(self, params: list[int], *, enabled: bool, private: bool) -> None:
        if not private:
            return
        if any(param in {47, 1047, 1049} for param in params):
            if enabled:
                self._enter_alternate_screen()
            else:
                self._exit_alternate_screen()

    def _enter_alternate_screen(self) -> None:
        if self._main_lines is not None:
            return
        self._main_lines = [line.copy() for line in self.lines]
        self._main_cursor_row = self.cursor_row
        self._main_cursor_col = self.cursor_col
        self._main_saved_cursor_row = self.saved_cursor_row
        self._main_saved_cursor_col = self.saved_cursor_col
        self.lines = [[]]
        self.cursor_row = 0
        self.cursor_col = 0
        self.saved_cursor_row = 0
        self.saved_cursor_col = 0

    def _exit_alternate_screen(self) -> None:
        if self._main_lines is None:
            return
        self.lines = self._main_lines or [[]]
        self.cursor_row = self._main_cursor_row
        self.cursor_col = self._main_cursor_col
        self.saved_cursor_row = self._main_saved_cursor_row
        self.saved_cursor_col = self._main_saved_cursor_col
        self._main_lines = None
        self._ensure_row(self.cursor_row)

    def _put_char(self, char: str) -> None:
        self._ensure_row(self.cursor_row)
        line = self.lines[self.cursor_row]
        while len(line) < self.cursor_col:
            line.append(" ")
        if self.cursor_col == len(line):
            line.append(char)
        else:
            line[self.cursor_col] = char
        self.cursor_col += 1
        if self.cursor_col >= self.cols:
            self.cursor_col = 0
            self._move_rows(1)

    def _ensure_row(self, row: int) -> None:
        while len(self.lines) <= row:
            self.lines.append([])
        self._trim_to_limit()

    def _move_rows(self, amount: int) -> None:
        self.cursor_row += amount
        self._ensure_row(self.cursor_row)

    def _trim_to_limit(self) -> None:
        limit = self._line_limit()
        if len(self.lines) <= limit:
            return
        overflow = len(self.lines) - limit
        del self.lines[:overflow]
        self.cursor_row = max(0, self.cursor_row - overflow)
        self.saved_cursor_row = max(0, self.saved_cursor_row - overflow)

    def _line_limit(self) -> int:
        if self._main_lines is not None:
            return max(1, self.rows)
        return max(1, self.scrollback_limit)

    @staticmethod
    def _param(params: list[int], default: int) -> int:
        return params[0] if params else default
