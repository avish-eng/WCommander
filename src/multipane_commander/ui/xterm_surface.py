from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
import time

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget

from multipane_commander.ui.terminal_surface import TerminalSurface

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEB_TERMINAL_AVAILABLE = True
except ImportError:
    WEB_TERMINAL_AVAILABLE = False


_MAX_PENDING_OUTPUT = 2 * 1024 * 1024
_MAX_PLAIN_OUTPUT = 200_000


def _asset_directory() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "xterm"


def update_draft_from_input(draft: str, data: bytes) -> tuple[str, list[str]]:
    """Track simple shell input for command history without parsing terminal output."""
    submitted: list[str] = []
    text = data.decode("utf-8", errors="ignore")
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\x1b":
            index = _skip_escape_sequence(text, index)
            continue
        if char in "\r\n":
            command = draft.strip()
            if command:
                submitted.append(command)
            draft = ""
        elif char in "\x08\x7f":
            draft = draft[:-1]
        elif char == "\x15":  # Ctrl+U
            draft = ""
        elif char == "\x17":  # Ctrl+W
            draft = draft.rstrip().rsplit(" ", 1)[0] if draft.strip() else ""
        elif char in "\x03\x04\x11\x1a":  # interrupt/EOF/resume/suspend
            draft = ""
        elif char >= " ":
            draft += char
        index += 1
    return draft, submitted


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


@lru_cache(maxsize=1)
def build_xterm_html() -> str:
    """Return a self-contained terminal page using the vendored xterm assets."""
    asset_dir = _asset_directory()
    css = (asset_dir / "xterm.min.css").read_text(encoding="utf-8")
    xterm_js = (asset_dir / "xterm.min.js").read_text(encoding="utf-8").replace(
        "</script>", "<\\/script>"
    )
    fit_js = (asset_dir / "xterm-addon-fit.min.js").read_text(encoding="utf-8").replace(
        "</script>", "<\\/script>"
    )
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{css}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: 100%; height: 100%; overflow: hidden; background: #111827; }}
#terminal {{ position: absolute; inset: 0; }}
</style>
</head>
<body>
<div id="terminal"></div>
<script>{xterm_js}</script>
<script>{fit_js}</script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
(function () {{
  var terminalElement = document.getElementById('terminal');
  var term = new Terminal({{
    fontFamily: 'Cascadia Mono, Consolas, "Courier New", monospace',
    fontSize: 13,
    lineHeight: 1.15,
    cursorBlink: true,
    cursorStyle: 'block',
    scrollback: 10000,
    convertEol: false,
    allowTransparency: false,
    theme: {{
      background: '#111827', foreground: '#e5e7eb',
      cursor: '#67e8f9', cursorAccent: '#111827',
      selectionBackground: '#47556999',
      black: '#111827', red: '#f87171', green: '#4ade80',
      yellow: '#facc15', blue: '#60a5fa', magenta: '#c084fc',
      cyan: '#22d3ee', white: '#d1d5db',
      brightBlack: '#6b7280', brightRed: '#fca5a5',
      brightGreen: '#86efac', brightYellow: '#fde047',
      brightBlue: '#93c5fd', brightMagenta: '#d8b4fe',
      brightCyan: '#67e8f9', brightWhite: '#f9fafb'
    }}
  }});
  var fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(terminalElement);
  window.mpcTerminal = term;

  function decodeBase64(value) {{
    var binary = atob(value);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }}

  function encodeBase64(value) {{
    var bytes = new TextEncoder().encode(value);
    var binary = '';
    for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }}

  new QWebChannel(qt.webChannelTransport, function (channel) {{
    var bridge = channel.objects.bridge;
    var readySent = false;

    bridge.write_data.connect(function (data) {{ term.write(decodeBase64(data)); }});
    bridge.paste_text.connect(function (text) {{ term.paste(text); }});
    term.onData(function (data) {{ bridge.send_input(encodeBase64(data)); }});
    term.onResize(function (size) {{ bridge.resize_terminal(size.cols, size.rows); }});

    term.attachCustomKeyEventHandler(function (event) {{
      if (event.type !== 'keydown') return true;
      var pasteShortcut =
        ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'v') ||
        (event.shiftKey && event.key === 'Insert');
      if (!pasteShortcut) return true;
      event.preventDefault();
      bridge.request_paste();
      return false;
    }});

    function fitTerminal() {{
      var dimensions = fit.proposeDimensions();
      if (!dimensions || dimensions.cols <= 0 || dimensions.rows <= 0) return;
      fit.fit();
      if (!readySent) {{
        readySent = true;
        bridge.terminal_ready();
      }}
    }}

    new ResizeObserver(function () {{ requestAnimationFrame(fitTerminal); }}).observe(terminalElement);
    document.fonts.ready.then(function () {{
      requestAnimationFrame(function () {{ requestAnimationFrame(fitTerminal); }});
    }});
  }});
}}());
</script>
</body>
</html>"""


class XtermBridge(QObject):
    """QWebChannel bridge between xterm.js and a Python terminal backend."""

    write_data = Signal(str)
    paste_text = Signal(str)
    input_received = Signal(bytes)
    paste_requested = Signal()
    terminal_resized = Signal(int, int)
    ready = Signal()

    @Slot(str)
    def send_input(self, encoded: str) -> None:
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return
        self.input_received.emit(data)

    @Slot()
    def request_paste(self) -> None:
        self.paste_requested.emit()

    @Slot(int, int)
    def resize_terminal(self, cols: int, rows: int) -> None:
        if cols > 0 and rows > 0:
            self.terminal_resized.emit(cols, rows)

    @Slot()
    def terminal_ready(self) -> None:
        self.ready.emit()


class XtermTerminalSurface(QFrame):
    """An xterm.js terminal widget with the API expected by ``TerminalDock``."""

    command_submitted = Signal(str)
    terminal_resized = Signal(int, int)
    accepts_immediate_input = True

    def __init__(self, parent: QWidget | None = None) -> None:
        if not WEB_TERMINAL_AVAILABLE:
            raise RuntimeError("PySide6-WebEngine is unavailable")
        super().__init__(parent)
        self.setObjectName("xtermTerminalSurface")
        self._sender = lambda _data: None
        self._submit_sequence = b"\r"
        self._local_echo = False
        self._input_ready = True
        self._pending_input: list[bytes] = []
        self._pending_output = bytearray()
        self._page_ready = False
        self._draft = ""
        self._plain_output = ""
        self._last_paste_at = 0.0
        self._last_paste_text = ""

        self._bridge = XtermBridge(self)
        self._bridge.input_received.connect(self._handle_input)
        self._bridge.paste_requested.connect(self._paste_clipboard)
        self._bridge.terminal_resized.connect(self._handle_resize)
        self._bridge.ready.connect(self._handle_ready)

        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        self._view = QWebEngineView(self)
        self._view.setObjectName("xtermWebView")
        self._view.page().setWebChannel(self._channel)
        self.setFocusProxy(self._view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._view)
        self._view.setHtml(build_xterm_html())

    def viewport(self) -> QWidget:
        return self._view

    def set_sender(self, sender) -> None:
        self._sender = sender

    def set_local_echo(self, enabled: bool) -> None:
        self._local_echo = enabled

    def set_submit_sequence(self, submit_sequence: bytes) -> None:
        self._submit_sequence = submit_sequence or b"\r"

    def set_input_ready(self, ready: bool) -> None:
        self._input_ready = ready
        if not ready or not self._pending_input:
            return
        pending, self._pending_input = self._pending_input, []
        for data in pending:
            self._sender(data)

    def input_ready(self) -> bool:
        return self._input_ready

    def append_output(self, text: str) -> None:
        if not text:
            return
        self._plain_output = (self._plain_output + text)[-_MAX_PLAIN_OUTPUT:]
        data = text.encode("utf-8", errors="replace")
        if self._page_ready:
            self._write_bytes(data)
            return
        self._pending_output.extend(data)
        if len(self._pending_output) > _MAX_PENDING_OUTPUT:
            del self._pending_output[: len(self._pending_output) - _MAX_PENDING_OUTPUT]

    def inject_command(self, command: str, *, run: bool) -> None:
        if not command:
            return
        data = command.encode("utf-8", errors="replace")
        if self._local_echo:
            self.append_output(command)
        self._send_bytes(data)
        self._draft += command
        if not run:
            return
        self._send_bytes(self._submit_sequence)
        if self._local_echo:
            self.append_output("\r\n")
        submitted = self._draft.strip()
        if submitted:
            self.command_submitted.emit(submitted)
        self.clear_draft()

    def current_draft(self) -> str:
        return self._draft

    def clear_draft(self) -> None:
        self._draft = ""

    def clear(self) -> None:
        self._pending_output.clear()
        self._plain_output = ""
        self.clear_draft()
        if self._page_ready:
            self._view.page().runJavaScript(
                "if (window.mpcTerminal) { window.mpcTerminal.clear(); }"
            )

    def copy(self) -> None:
        if not self._page_ready:
            return

        def copy_selection(value) -> None:
            if isinstance(value, str) and value:
                QApplication.clipboard().setText(value)

        self._view.page().runJavaScript(
            "window.mpcTerminal ? window.mpcTerminal.getSelection() : ''",
            copy_selection,
        )

    def selectAll(self) -> None:  # noqa: N802 - Qt-compatible API
        if self._page_ready:
            self._view.page().runJavaScript(
                "if (window.mpcTerminal) { window.mpcTerminal.selectAll(); }"
            )

    def toPlainText(self) -> str:  # noqa: N802 - Qt-compatible API
        return self._plain_output

    def _handle_input(self, data: bytes) -> None:
        self._track_draft(data)
        self._send_bytes(data)

    def _paste_clipboard(self) -> None:
        self.paste_from_clipboard()

    def paste_from_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        now = time.monotonic()
        if text == self._last_paste_text and now - self._last_paste_at < 0.25:
            return
        self._last_paste_text = text
        self._last_paste_at = now
        self._bridge.paste_text.emit(text)

    def _track_draft(self, data: bytes) -> None:
        self._draft, submitted = update_draft_from_input(self._draft, data)
        for command in submitted:
            self.command_submitted.emit(command)

    def _send_bytes(self, data: bytes) -> None:
        if not self._input_ready:
            self._pending_input.append(data)
            return
        self._sender(data)

    def _write_bytes(self, data: bytes) -> None:
        self._bridge.write_data.emit(base64.b64encode(data).decode("ascii"))

    def _handle_resize(self, cols: int, rows: int) -> None:
        self.terminal_resized.emit(cols, rows)

    def _handle_ready(self) -> None:
        self._page_ready = True
        if self._pending_output:
            data = bytes(self._pending_output)
            self._pending_output.clear()
            self._write_bytes(data)


def create_terminal_surface(parent: QWidget | None = None) -> XtermTerminalSurface | TerminalSurface:
    """Use xterm.js when Qt WebEngine is installed, with the old widget as fallback."""
    if WEB_TERMINAL_AVAILABLE:
        return XtermTerminalSurface(parent)
    return TerminalSurface(parent)
