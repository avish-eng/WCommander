from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget

from multipane_commander.terminal.deep.input_tracker import InputDraftTracker

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEB_TERMINAL_AVAILABLE = True
except ImportError:
    WEB_TERMINAL_AVAILABLE = False

if WEB_TERMINAL_AVAILABLE:

    class _DeepWebView(QWebEngineView):
        def contextMenuEvent(self, event) -> None:  # type: ignore[override]
            event.ignore()

else:
    _DeepWebView = None


_MAX_PENDING_OUTPUT = 4 * 1024 * 1024
_MAX_PLAIN_OUTPUT = 200_000
_MAX_REPLAY_BYTES = 4 * 1024 * 1024
_FLUSH_INTERVAL_MS = 16
_MAX_PENDING_INPUT = 64 * 1024

_DEFAULT_THEME = {
    "background": "#111827",
    "foreground": "#e5e7eb",
    "cursor": "#67e8f9",
    "cursorAccent": "#111827",
    "selectionBackground": "#47556999",
    "black": "#111827",
    "red": "#f87171",
    "green": "#4ade80",
    "yellow": "#facc15",
    "blue": "#60a5fa",
    "magenta": "#c084fc",
    "cyan": "#22d3ee",
    "white": "#d1d5db",
    "brightBlack": "#6b7280",
    "brightRed": "#fca5a5",
    "brightGreen": "#86efac",
    "brightYellow": "#fde047",
    "brightBlue": "#93c5fd",
    "brightMagenta": "#d8b4fe",
    "brightCyan": "#67e8f9",
    "brightWhite": "#f9fafb",
}


def _asset_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "xterm"


@lru_cache(maxsize=1)
def build_deep_terminal_html() -> str:
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
#terminal {{ position: absolute; inset: 0; padding: 4px 0 0 6px; }}
.xterm .xterm-viewport {{ scrollbar-width: thin; }}
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
    fontFamily: 'Cascadia Mono, Consolas, "SF Mono", Menlo, Monaco, "Courier New", monospace',
    fontSize: 13,
    lineHeight: 1.15,
    letterSpacing: 0,
    cursorBlink: true,
    cursorStyle: 'block',
    scrollback: 50000,
    convertEol: false,
    allowTransparency: false,
    macOptionIsMeta: true,
    smoothScrollDuration: 80,
    fastScrollModifier: 'alt',
    windowsPty: {{}},
    theme: {_theme_literal(_DEFAULT_THEME)}
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

  var searchQuery = null;
  var searchCase = false;
  var searchMatches = [];
  var searchIndex = -1;

  function clearSearch() {{
    searchQuery = null;
    searchMatches = [];
    searchIndex = -1;
    if (term.hasSelection()) term.clearSelection();
  }}

  function scanMatches(query, caseSensitive) {{
    searchMatches = [];
    searchIndex = -1;
    searchQuery = query;
    searchCase = caseSensitive;
    if (!query) return;
    var needle = caseSensitive ? query : query.toLowerCase();
    var buffer = term.buffer.active;
    for (var row = 0; row < buffer.length; row++) {{
      var line = buffer.getLine(row);
      if (!line) continue;
      var text = line.translateToString(true);
      var haystack = caseSensitive ? text : text.toLowerCase();
      var index = haystack.indexOf(needle);
      while (index !== -1) {{
        searchMatches.push({{row: row, column: index, length: query.length}});
        index = haystack.indexOf(needle, index + Math.max(1, needle.length));
      }}
    }}
  }}

  window.mpcSearch = function (query, direction, caseSensitive) {{
    if (!query) {{ clearSearch(); return JSON.stringify({{count: 0, index: -1}}); }}
    if (query !== searchQuery || caseSensitive !== searchCase) {{
      scanMatches(query, caseSensitive);
    }}
    if (!searchMatches.length) {{
      if (term.hasSelection()) term.clearSelection();
      return JSON.stringify({{count: 0, index: -1}});
    }}
    searchIndex += direction < 0 ? -1 : 1;
    if (searchIndex < 0) searchIndex = searchMatches.length - 1;
    if (searchIndex >= searchMatches.length) searchIndex = 0;
    var match = searchMatches[searchIndex];
    term.select(match.column, match.row, match.length);
    term.scrollToLine(match.row);
    return JSON.stringify({{count: searchMatches.length, index: searchIndex}});
  }};

  window.mpcClearSearch = function () {{ clearSearch(); }};
  window.mpcGetSelection = function () {{ return term.getSelection(); }};
  window.mpcSelectAll = function () {{ term.selectAll(); }};
  window.mpcClear = function () {{ term.clear(); }};
  window.mpcReset = function () {{ term.reset(); }};
  window.mpcFocus = function () {{ term.focus(); }};
  window.mpcGetFontSize = function () {{ return term.options.fontSize || 13; }};
  window.mpcSetFontSize = function (size) {{
    size = Math.max(6, Math.min(40, Math.round(size)));
    term.options.fontSize = size;
    try {{ fit.fit(); }} catch (error) {{}}
    if (bridge) bridge.notify_font_size(size);
    return size;
  }};
  window.mpcSetFontFamily = function (family) {{
    if (family) term.options.fontFamily = family;
    try {{ fit.fit(); }} catch (error) {{}}
  }};
  window.mpcSetTheme = function (theme) {{
    if (theme) term.options.theme = theme;
  }};

  var bridge = null;
  var readySent = false;

  new QWebChannel(qt.webChannelTransport, function (channel) {{
    bridge = channel.objects.bridge;
    bridge.write_data.connect(function (data) {{ term.write(decodeBase64(data)); }});
    bridge.paste_text.connect(function (text) {{ term.paste(text); }});
    bridge.clear_requested.connect(function () {{ term.clear(); }});
    bridge.focus_requested.connect(function () {{ term.focus(); }});
    bridge.font_family_requested.connect(function (family) {{ window.mpcSetFontFamily(family); }});
    bridge.theme_requested.connect(function (theme) {{ window.mpcSetTheme(theme); }});

    term.onData(function (data) {{ bridge.send_input(encodeBase64(data)); }});
    term.onResize(function (size) {{ bridge.resize_terminal(size.cols, size.rows); }});
    term.onTitleChange(function (title) {{ bridge.set_title(title); }});
    term.onBell(function () {{ bridge.notify_bell(); }});

    term.attachCustomKeyEventHandler(function (event) {{
      if (event.type !== 'keydown') return true;
      var isMac = /Mac|iPhone|iPad/.test(navigator.platform);
      var modifier = event.ctrlKey || event.metaKey;
      var key = event.key;

      if (modifier && key === 'Insert') {{
        var selection = term.getSelection();
        if (selection) {{ bridge.copy_text(selection); event.preventDefault(); return false; }}
        return true;
      }}
      if (event.shiftKey && key === 'Insert') {{
        bridge.request_paste();
        event.preventDefault();
        return false;
      }}
      if (modifier && (key === 'f' || key === 'F')) {{
        bridge.request_search();
        event.preventDefault();
        return false;
      }}
      if (modifier && (key === '=' || key === '+' || key === '-' || key === '_' || key === '0')) {{
        var current = term.options.fontSize || 13;
        if (key === '0') window.mpcSetFontSize(13);
        else if (key === '-' || key === '_') window.mpcSetFontSize(current - 1);
        else window.mpcSetFontSize(current + 1);
        event.preventDefault();
        return false;
      }}
      return true;
    }});

    var linkProvider = {{
      provideLinks: function (bufferLineNumber, callback) {{
        var line = term.buffer.active.getLine(bufferLineNumber - 1);
        if (!line) {{ callback(undefined); return; }}
        var text = line.translateToString(true);
        var pattern = /(?:https?:\\/\\/|file:\\/\\/)[^\\s'"<>()\\[\\]]+/g;
        var links = [];
        var match;
        while ((match = pattern.exec(text)) !== null) {{
          (function (value, start) {{
            links.push({{
              range: {{
                start: {{x: start + 1, y: bufferLineNumber}},
                end: {{x: start + value.length, y: bufferLineNumber}}
              }},
              text: value,
              activate: function (_event, uri) {{ bridge.open_link(uri); }}
            }});
          }})(match[0], match.index);
        }}
        callback(links.length ? links : undefined);
      }}
    }};
    term.registerLinkProvider(linkProvider);

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


def _theme_literal(theme: dict[str, str]) -> str:
    import json

    return json.dumps(theme)


class DeepTerminalBridge(QObject):
    write_data = Signal(str)
    paste_text = Signal(str)
    clear_requested = Signal()
    focus_requested = Signal()
    font_family_requested = Signal(str)
    theme_requested = Signal(str)

    input_received = Signal(bytes)
    paste_requested = Signal()
    terminal_resized = Signal(int, int)
    copy_requested = Signal(str)
    open_link_requested = Signal(str)
    title_changed = Signal(str)
    bell = Signal()
    font_size_changed = Signal(int)
    search_requested = Signal()
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

    @Slot(str)
    def copy_text(self, text: str) -> None:
        self.copy_requested.emit(text)

    @Slot(str)
    def open_link(self, uri: str) -> None:
        self.open_link_requested.emit(uri)

    @Slot(str)
    def set_title(self, title: str) -> None:
        self.title_changed.emit(title)

    @Slot()
    def request_search(self) -> None:
        self.search_requested.emit()

    @Slot()
    def notify_bell(self) -> None:
        self.bell.emit()

    @Slot(int)
    def notify_font_size(self, size: int) -> None:
        self.font_size_changed.emit(size)

    @Slot()
    def terminal_ready(self) -> None:
        self.ready.emit()


class DeepTerminalSurface(QFrame):
    command_submitted = Signal(str)
    terminal_resized = Signal(int, int)
    link_activated = Signal(str)
    search_requested = Signal()
    search_result = Signal(int, int)
    font_size_changed = Signal(int)
    title_received = Signal(str)
    bell_received = Signal()

    accepts_immediate_input = True

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        web_view_factory=None,
        flush_interval_ms: int = _FLUSH_INTERVAL_MS,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("deepTerminalSurface")
        self._sender = lambda _data: None
        self._submit_sequence = b"\r"
        self._local_echo = False
        self._input_ready = True
        self._page_ready = False
        self._pending_input: list[bytes] = []
        self._pending_input_bytes = 0
        self._pending_output = bytearray()
        self._replay_chunks: list[bytes] = []
        self._replay_bytes = 0
        self._plain_chunks: list[str] = []
        self._plain_length = 0
        self._tracker = InputDraftTracker()
        self._last_paste_at = 0.0
        self._last_paste_text = ""
        self._font_size = 13

        self._bridge = DeepTerminalBridge(self)
        self._bridge.input_received.connect(self._handle_input)
        self._bridge.paste_requested.connect(self._paste_clipboard)
        self._bridge.terminal_resized.connect(self._handle_resize)
        self._bridge.copy_requested.connect(self._handle_copy)
        self._bridge.open_link_requested.connect(self.link_activated.emit)
        self._bridge.title_changed.connect(self.title_received.emit)
        self._bridge.bell.connect(self.bell_received.emit)
        self._bridge.font_size_changed.connect(self._handle_font_size)
        self._bridge.search_requested.connect(self.search_requested.emit)
        self._bridge.ready.connect(self._handle_ready)

        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(max(1, flush_interval_ms))
        self._flush_timer.timeout.connect(self._flush_output)

        self._view: QWidget
        if web_view_factory is not None:
            self._view = web_view_factory(self)
        else:
            self._channel = QWebChannel(self)
            self._channel.registerObject("bridge", self._bridge)
            view_class = _DeepWebView or QWebEngineView
            self._view = view_class(self)
            self._view.setObjectName("deepTerminalWebView")
            self._view.page().setWebChannel(self._channel)
            self._view.setHtml(build_deep_terminal_html())
        self.setFocusProxy(self._view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._view)

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
        self._pending_input_bytes = 0
        for data in pending:
            self._sender(data)

    def input_ready(self) -> bool:
        return self._input_ready

    def append_output(self, data: bytes | str) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        if not data:
            return
        self._append_plain(data)
        self._pending_output.extend(data)
        if len(self._pending_output) >= _MAX_PENDING_OUTPUT:
            self._flush_output()
            return
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def inject_command(self, command: str, *, run: bool) -> None:
        if not command:
            return
        data = command.encode("utf-8", errors="replace")
        if self._local_echo:
            self.append_output(command)
        self._send_bytes(data)
        self._tracker.set_draft(self._tracker.draft + command)
        if not run:
            return
        self._send_bytes(self._submit_sequence)
        if self._local_echo:
            self.append_output("\r\n")
        submitted = self._tracker.draft.strip()
        if submitted:
            self.command_submitted.emit(submitted)
        self._tracker.reset()

    def current_draft(self) -> str:
        return self._tracker.draft

    def clear_draft(self) -> None:
        self._tracker.reset()

    def clear(self) -> None:
        self._flush_timer.stop()
        self._pending_output.clear()
        self._replay_chunks = []
        self._replay_bytes = 0
        self._plain_chunks = []
        self._plain_length = 0
        self._tracker.reset()
        if self._page_ready:
            self._run_js("window.mpcClear && window.mpcClear();")

    def copy(self) -> None:
        if self._page_ready:
            self._run_js(
                "window.mpcGetSelection ? window.mpcGetSelection() : ''",
                self._handle_copy,
            )
            return
        self._bridge.copy_requested.emit("")

    def selectAll(self) -> None:  # noqa: N802 - Qt-compatible API
        if self._page_ready:
            self._run_js("window.mpcSelectAll && window.mpcSelectAll();")

    def paste_from_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        now = time.monotonic()
        if text == self._last_paste_text and now - self._last_paste_at < 0.05:
            return
        self._last_paste_text = text
        self._last_paste_at = now
        if self._page_ready:
            self._bridge.paste_text.emit(text)
        else:
            self._send_bytes(text.encode("utf-8", errors="replace"))

    def focus_input(self) -> None:
        if self._page_ready:
            self._run_js("window.mpcFocus && window.mpcFocus();")
        self._view.setFocus()

    def search(self, query: str, *, direction: int = 1, case_sensitive: bool = False) -> None:
        if not self._page_ready:
            return
        script = "window.mpcSearch ? window.mpcSearch({query}, {direction}, {case}) : '{{}}'".format(
            query=_json_literal(query),
            direction=int(direction),
            case="true" if case_sensitive else "false",
        )
        self._run_js(script, self._handle_search_result)

    def clear_search(self) -> None:
        if self._page_ready:
            self._run_js("window.mpcClearSearch && window.mpcClearSearch();")

    def set_font_size(self, size: int) -> None:
        size = max(6, min(40, int(size)))
        self._font_size = size
        if self._page_ready:
            self._run_js(f"window.mpcSetFontSize && window.mpcSetFontSize({size});")

    def font_size(self) -> int:
        return self._font_size

    def apply_theme(self, theme: dict[str, str]) -> None:
        if self._page_ready:
            self._bridge.theme_requested.emit(_json_literal(theme))

    def set_font_family(self, family: str) -> None:
        if self._page_ready:
            self._bridge.font_family_requested.emit(family)

    def toPlainText(self) -> str:  # noqa: N802 - Qt-compatible API
        return "".join(self._plain_chunks)

    def _handle_input(self, data: bytes) -> None:
        for command in self._tracker.feed(data):
            self.command_submitted.emit(command)
        self._send_bytes(data)

    def _handle_copy(self, text) -> None:
        if isinstance(text, str) and text:
            QApplication.clipboard().setText(text)

    def _handle_search_result(self, result) -> None:
        parsed = _parse_search_result(result)
        if parsed is not None:
            count, index = parsed
            self.search_result.emit(count, index)

    def _handle_resize(self, cols: int, rows: int) -> None:
        self.terminal_resized.emit(cols, rows)

    def _handle_font_size(self, size: int) -> None:
        self._font_size = max(6, min(40, int(size)))
        self.font_size_changed.emit(self._font_size)

    def _handle_ready(self) -> None:
        self._page_ready = True
        for chunk in self._replay_chunks:
            self._bridge.write_data.emit(base64.b64encode(chunk).decode("ascii"))
        self._replay_chunks = []
        self._replay_bytes = 0
        self._flush_output()
        self.set_font_size(self._font_size)

    def _paste_clipboard(self) -> None:
        self.paste_from_clipboard()

    def _send_bytes(self, data: bytes) -> None:
        if not data:
            return
        if not self._input_ready:
            if self._pending_input_bytes < _MAX_PENDING_INPUT:
                self._pending_input.append(data)
                self._pending_input_bytes += len(data)
            return
        self._sender(data)

    def _flush_output(self) -> None:
        if not self._pending_output:
            return
        data = bytes(self._pending_output)
        self._pending_output.clear()
        self._replay_chunks.append(data)
        self._replay_bytes += len(data)
        while self._replay_bytes > _MAX_REPLAY_BYTES and len(self._replay_chunks) > 1:
            dropped = self._replay_chunks.pop(0)
            self._replay_bytes -= len(dropped)
        if self._page_ready:
            self._bridge.write_data.emit(base64.b64encode(data).decode("ascii"))

    def _append_plain(self, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        self._plain_chunks.append(text)
        self._plain_length += len(text)
        while self._plain_length > _MAX_PLAIN_OUTPUT and len(self._plain_chunks) > 1:
            dropped = self._plain_chunks.pop(0)
            self._plain_length -= len(dropped)

    def _run_js(self, script: str, callback=None) -> None:
        page_getter = getattr(self._view, "page", None)
        page = page_getter() if callable(page_getter) else None
        if page is None:
            return
        run = getattr(page, "runJavaScript", None)
        if run is None:
            return
        if callback is None:
            run(script)
        else:
            run(script, callback)


def _json_literal(value) -> str:
    import json

    return json.dumps(value)


def _parse_search_result(result) -> tuple[int, int] | None:
    import json

    if not isinstance(result, str):
        return None
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    count = payload.get("count")
    index = payload.get("index")
    if isinstance(count, int) and isinstance(index, int):
        return count, index
    return None


def create_deep_surface(parent: QWidget | None = None) -> DeepTerminalSurface:
    if not WEB_TERMINAL_AVAILABLE:
        raise RuntimeError("PySide6-WebEngine is required for the Deep terminal")
    return DeepTerminalSurface(parent)
