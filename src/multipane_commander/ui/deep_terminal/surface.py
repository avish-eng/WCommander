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


def _read_bundle(name: str) -> str:
    text = (_asset_directory() / name).read_text(encoding="utf-8")
    return text.replace("</script>", "<\\/script>")


_DEFAULT_FONT_FAMILY = (
    'Consolas, Cascadia Mono, "SF Mono", Menlo, Monaco, "DejaVu Sans Mono", '
    '"Courier New", monospace'
)
_DEFAULT_FONT_SIZE = 14
XTERM_VERSION = "6.0.0"
_MIN_FONT_SIZE = 6
_MAX_FONT_SIZE = 40


def _clamp_font_size(size: int) -> int:
    return max(_MIN_FONT_SIZE, min(_MAX_FONT_SIZE, int(size)))


@lru_cache(maxsize=8)
def build_deep_terminal_html(
    gpu_renderer: bool = False,
    font_family: str = "",
    font_size: int = _DEFAULT_FONT_SIZE,
) -> str:
    asset_dir = _asset_directory()
    css = (asset_dir / "xterm.min.css").read_text(encoding="utf-8")
    xterm_js = _read_bundle("xterm.min.js")
    fit_js = _read_bundle("xterm-addon-fit.min.js")
    unicode11_js = _read_bundle("xterm-addon-unicode11.min.js")
    search_js = _read_bundle("xterm-addon-search.min.js")
    web_links_js = _read_bundle("xterm-addon-web-links.min.js")
    webgl_js = _read_bundle("xterm-addon-webgl.min.js")
    resolved_family = font_family.strip() or _DEFAULT_FONT_FAMILY
    resolved_size = _clamp_font_size(font_size)
    # The DOM renderer draws text through Chromium's normal text stack and is
    # visibly crisper at fractional display scaling; WebGL renders glyphs from
    # a texture atlas and is only worth it for very high output throughput.
    webgl_script = f"<script>{webgl_js}</script>\n" if gpu_renderer else ""
    webgl_load = (
        "  try {\n"
        "    var webgl = new WebglAddon.WebglAddon();\n"
        "    webgl.onContextLoss(function () { webgl.dispose(); });\n"
        "    term.loadAddon(webgl);\n"
        "  } catch (webglError) {}\n"
        if gpu_renderer
        else ""
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
<script>{unicode11_js}</script>
<script>{search_js}</script>
<script>{web_links_js}</script>
{webgl_script}<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
(function () {{
  var terminalElement = document.getElementById('terminal');
  var defaultFontSize = {resolved_size};
  var term = new Terminal({{
    allowProposedApi: true,
    fontFamily: {_json_literal(resolved_family)},
    fontSize: {resolved_size},
    lineHeight: 1.15,
    letterSpacing: 0,
    cursorBlink: true,
    cursorStyle: 'block',
    cursorInactiveStyle: 'outline',
    scrollback: 50000,
    convertEol: false,
    allowTransparency: false,
    macOptionIsMeta: true,
    smoothScrollDuration: 80,
    fastScrollModifier: 'alt',
    rescaleOverlappingGlyphs: true,
    scrollOnUserInput: true,
    windowsPty: {{}},
    linkHandler: {{
      activate: function (_event, text) {{ if (bridge) bridge.open_link(text); }}
    }},
    theme: {_theme_literal(_DEFAULT_THEME)}
  }});
  var fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  try {{
    var unicode11 = new Unicode11Addon.Unicode11Addon();
    term.loadAddon(unicode11);
    term.unicode.activeVersion = '11';
  }} catch (unicodeError) {{}}
  var searchAddon = new SearchAddon.SearchAddon({{ highlightLimit: 2000 }});
  term.loadAddon(searchAddon);
  searchAddon.onDidChangeResults(function (event) {{
    if (bridge) bridge.search_results(event.resultCount, event.resultIndex);
  }});
  try {{
    var webLinks = new WebLinksAddon.WebLinksAddon(function (_event, uri) {{
      if (bridge) bridge.open_link(uri);
    }});
    term.loadAddon(webLinks);
  }} catch (linkError) {{}}
  term.open(terminalElement);
{webgl_load}  window.mpcTerminal = term;

  var logicalFontSize = defaultFontSize;
  var baseLineHeight = 1.15;
  var baseLetterSpacing = 0;
  var lastDevicePixelRatio = window.devicePixelRatio || 1;

  function measureAdvance(family, size) {{
    var probe = document.createElement('span');
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    probe.style.whiteSpace = 'pre';
    probe.style.fontFamily = family;
    probe.style.fontSize = size + 'px';
    probe.textContent = new Array(101).join('M');
    document.body.appendChild(probe);
    var advance = probe.getBoundingClientRect().width / 100;
    document.body.removeChild(probe);
    return advance;
  }}

  // At fractional display scaling (Windows 120%/150%) a monospace grid lands
  // glyphs on shifting subpixel phases, producing uneven stems and clipped
  // digit tops. Snapping the glyph ppem, character advance and cell height to
  // whole device pixels keeps every cell pixel-aligned while the logical size
  // (what zoom and config store) stays an integer.
  function snapTerminalMetrics() {{
    var dpr = window.devicePixelRatio || 1;
    lastDevicePixelRatio = dpr;
    var fractional = Math.abs(dpr - Math.round(dpr)) > 0.001;
    if (!fractional) {{
      term.options.fontSize = logicalFontSize;
      term.options.letterSpacing = baseLetterSpacing;
      term.options.lineHeight = baseLineHeight;
      return;
    }}
    var devicePixels = Math.max(1, Math.round(logicalFontSize * dpr));
    var cssSize = devicePixels / dpr;
    term.options.fontSize = cssSize;
    var advance = measureAdvance(term.options.fontFamily, cssSize);
    if (advance > 0) {{
      term.options.letterSpacing = Math.round(advance * dpr) / dpr - advance;
    }}
    term.options.lineHeight = Math.max(
      devicePixels,
      Math.round(cssSize * baseLineHeight * dpr)
    ) / (cssSize * dpr);
  }}

  snapTerminalMetrics();

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

  var searchOptions = {{
    decorations: {{
      matchBackground: '#4a3b00',
      matchBorder: '#c8a600',
      matchOverviewRuler: '#c8a600',
      activeMatchBackground: '#c8a600',
      activeMatchBorder: '#ffd000',
      activeMatchColorOverviewRuler: '#ffd000'
    }}
  }};

  window.mpcSearch = function (query, direction, caseSensitive) {{
    if (!query) {{ window.mpcClearSearch(); return; }}
    var options = {{
      caseSensitive: !!caseSensitive,
      decorations: searchOptions.decorations
    }};
    try {{
      if (direction < 0) searchAddon.findPrevious(query, options);
      else searchAddon.findNext(query, options);
    }} catch (searchError) {{}}
  }};

  window.mpcClearSearch = function () {{
    try {{
      searchAddon.clearDecorations();
      searchAddon.clearActiveDecoration();
    }} catch (searchError) {{}}
  }};
  window.mpcGetSelection = function () {{ return term.getSelection(); }};
  window.mpcSelectAll = function () {{ term.selectAll(); }};
  window.mpcClear = function () {{ term.clear(); }};
  window.mpcReset = function () {{ term.reset(); }};
  window.mpcFocus = function () {{ term.focus(); }};
  window.mpcGetFontSize = function () {{ return logicalFontSize; }};
  window.mpcSetFontSize = function (size) {{
    logicalFontSize = Math.max(6, Math.min(40, Math.round(size)));
    snapTerminalMetrics();
    try {{ fit.fit(); }} catch (error) {{}}
    if (bridge) bridge.notify_font_size(logicalFontSize);
    return logicalFontSize;
  }};
  window.mpcSetFontFamily = function (family) {{
    if (family) term.options.fontFamily = family;
    snapTerminalMetrics();
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
      var ctrl = event.ctrlKey;
      var meta = event.metaKey;
      var shift = event.shiftKey;

      // A focused QWebEngineView swallows keys before the host app's Qt
      // shortcuts run, so clipboard chords must be handled here.
      var copyChord =
        (isMac && meta && (key === 'c' || key === 'C')) ||
        (ctrl && shift && (key === 'c' || key === 'C')) ||
        (ctrl && key === 'Insert');
      var pasteChord =
        (isMac && meta && (key === 'v' || key === 'V')) ||
        (ctrl && (key === 'v' || key === 'V')) ||
        (shift && key === 'Insert');

      if (pasteChord) {{
        bridge.request_paste();
        event.preventDefault();
        return false;
      }}
      if (copyChord) {{
        var chordSelection = term.getSelection();
        if (chordSelection) bridge.copy_text(chordSelection);
        event.preventDefault();
        return false;
      }}
      if (ctrl && !shift && (key === 'c' || key === 'C') && term.hasSelection()) {{
        // Ctrl+C copies when text is selected, otherwise interrupts.
        bridge.copy_text(term.getSelection());
        event.preventDefault();
        return false;
      }}
      if (modifier && (key === 'f' || key === 'F')) {{
        bridge.request_search();
        event.preventDefault();
        return false;
      }}
      if (modifier && (key === '=' || key === '+' || key === '-' || key === '_' || key === '0')) {{
        if (key === '0') window.mpcSetFontSize(defaultFontSize);
        else if (key === '-' || key === '_') window.mpcSetFontSize(logicalFontSize - 1);
        else window.mpcSetFontSize(logicalFontSize + 1);
        event.preventDefault();
        return false;
      }}
      return true;
    }});

    function fitTerminal() {{
      if ((window.devicePixelRatio || 1) !== lastDevicePixelRatio) {{
        snapTerminalMetrics();
      }}
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
    search_results_received = Signal(int, int)
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

    @Slot(int, int)
    def search_results(self, count: int, index: int) -> None:
        self.search_results_received.emit(count, index)

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
        gpu_renderer: bool = False,
        font_family: str = "",
        font_size: int = _DEFAULT_FONT_SIZE,
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
        self._font_family = font_family.strip()
        self._default_font_size = _clamp_font_size(font_size)
        self._font_size = self._default_font_size
        self._page_dpr: float | None = None

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
        self._bridge.search_results_received.connect(self.search_result.emit)
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
            self._view.setHtml(
                build_deep_terminal_html(
                    gpu_renderer,
                    self._font_family,
                    self._default_font_size,
                )
            )
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
        script = "window.mpcSearch ? window.mpcSearch({query}, {direction}, {case}) : undefined".format(
            query=_json_literal(query),
            direction=int(direction),
            case="true" if case_sensitive else "false",
        )
        self._run_js(script)

    def clear_search(self) -> None:
        if self._page_ready:
            self._run_js("window.mpcClearSearch && window.mpcClearSearch();")

    def set_font_size(self, size: int) -> None:
        size = _clamp_font_size(size)
        self._font_size = size
        if self._page_ready:
            self._run_js(f"window.mpcSetFontSize && window.mpcSetFontSize({size});")

    def reset_font_size(self) -> None:
        self.set_font_size(self._default_font_size)

    def font_size(self) -> int:
        return self._font_size

    def font_family(self) -> str:
        return self._font_family

    def page_device_pixel_ratio(self) -> float | None:
        return self._page_dpr

    def save_snapshot(self, path) -> bool:
        pixmap = self.grab()
        if pixmap.isNull() or pixmap.width() <= 0:
            return False
        return pixmap.save(str(path))

    def apply_theme(self, theme: dict[str, str]) -> None:
        if self._page_ready:
            self._bridge.theme_requested.emit(_json_literal(theme))

    def set_font_family(self, family: str) -> None:
        self._font_family = family.strip()
        resolved = self._font_family or _DEFAULT_FONT_FAMILY
        if self._page_ready:
            self._bridge.font_family_requested.emit(resolved)

    def toPlainText(self) -> str:  # noqa: N802 - Qt-compatible API
        return "".join(self._plain_chunks)

    def _handle_input(self, data: bytes) -> None:
        # The session must see the bytes before the submit event is published,
        # so history gating can rely on the session's prompt/draft state.
        self._send_bytes(data)
        for command in self._tracker.feed(data):
            self.command_submitted.emit(command)

    def _handle_copy(self, text) -> None:
        if isinstance(text, str) and text:
            QApplication.clipboard().setText(text)

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
        self._run_js(
            "window.devicePixelRatio || 1",
            self._handle_page_dpr,
        )

    def _handle_page_dpr(self, value) -> None:
        if isinstance(value, (int, float)) and value > 0:
            self._page_dpr = float(value)

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


def create_deep_surface(
    parent: QWidget | None = None,
    *,
    gpu_renderer: bool = False,
    font_family: str = "",
    font_size: int = _DEFAULT_FONT_SIZE,
) -> DeepTerminalSurface:
    if not WEB_TERMINAL_AVAILABLE:
        raise RuntimeError("PySide6-WebEngine is required for the Deep terminal")
    return DeepTerminalSurface(
        parent,
        gpu_renderer=gpu_renderer,
        font_family=font_family,
        font_size=font_size,
    )
