from __future__ import annotations

import base64
import os
import platform
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

# Namespace UUID for WCommander CC sessions — ensures our deterministic UUIDs
# never collide with sessions the user started manually from the terminal.
_WC_SESSION_NS = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


def _session_id_for(path: Path) -> str:
    """Stable UUID v5 for this directory path, namespaced to WCommander."""
    return str(uuid.uuid5(_WC_SESSION_NS, str(path.resolve())))

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebChannel import QWebChannel

    _WEB_AVAILABLE = True
except ImportError:
    _WEB_AVAILABLE = False


# xterm.js loaded from jsDelivr CDN (cached after first load).
# qrc:///qtwebchannel/qwebchannel.js is built into Qt — no internet needed.
_XTERM_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 100%; height: 100%; overflow: hidden; background: #1e1e2e; }
/* No padding on #terminal — FitAddon measures getBoundingClientRect()
   and padding shrinks reported width, causing col miscounting. */
#terminal { position: absolute; inset: 0; }
#msg { position: absolute; inset: 0; display: flex; align-items: center;
       justify-content: center; color: #a6adc8;
       font: 13px/1.5 -apple-system, system-ui, sans-serif;
       padding: 16px; text-align: center; }
</style>
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css">
</head>
<body>
<div id="msg">Loading terminal…</div>
<div id="terminal" style="display:none"></div>
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
(function () {
  var msg = document.getElementById('msg');
  var termDiv = document.getElementById('terminal');

  if (typeof Terminal === 'undefined') {
    msg.textContent =
      'xterm.js requires internet access on first use (loads from CDN). ' +
      'Check connection and reload.';
    return;
  }

  var term = new Terminal({
    fontFamily: 'Menlo, Monaco, "Courier New", monospace',
    fontSize: 13,
    lineHeight: 1.2,
    cursorBlink: true,
    scrollback: 10000,
    allowTransparency: false,   // solid backgrounds — needed for reverse-video highlights
    convertEol: false,          // PTY handles CR/LF; don't double-convert
    theme: {
      background:    '#1e1e2e', foreground:   '#cdd6f4',
      cursor:        '#f5c2e7', cursorAccent: '#1e1e2e',
      selectionBackground: '#45475a80',
      black:   '#45475a', red:     '#f38ba8', green:   '#a6e3a1',
      yellow:  '#f9e2af', blue:    '#89b4fa', magenta: '#f5c2e7',
      cyan:    '#94e2d5', white:   '#bac2de',
      brightBlack:   '#585b70', brightRed:     '#f38ba8',
      brightGreen:   '#a6e3a1', brightYellow:  '#f9e2af',
      brightBlue:    '#89b4fa', brightMagenta: '#f5c2e7',
      brightCyan:    '#94e2d5', brightWhite:   '#a6adc8'
    }
  });

  var fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(termDiv);
  termDiv.style.display = '';
  msg.style.display = 'none';

  // ── Fix 1: wrapping ────────────────────────────────────────────────────────
  // FitAddon must run AFTER fonts are loaded and the DOM has its final size.
  // document.fonts.ready waits for webfonts; the double rAF gives Chromium
  // time to finish layout so getBoundingClientRect() returns the real width.
  //
  // IMPORTANT: js_ready() fires AFTER resize_pty so Python starts the Claude
  // process knowing the correct terminal dimensions, avoiding garbled TUI output.
  var _jsReadySent = false;
  function doFit(bridge) {
    var dims = fit.proposeDimensions();
    if (!dims || isNaN(dims.cols) || dims.cols <= 0) {
      // Font metrics not ready yet — retry next frame
      requestAnimationFrame(function () { doFit(bridge); });
      return;
    }
    fit.fit();
    if (bridge) { bridge.resize_pty(term.cols, term.rows); }
    term.focus();
    if (bridge && !_jsReadySent) { _jsReadySent = true; bridge.js_ready(); }
  }

  // ResizeObserver handles all subsequent container resizes (splitter drags etc.)
  new ResizeObserver(function () { fit.fit(); }).observe(termDiv);

  // ── Fix 2: '/' intercepted by Chromium find-on-type ───────────────────────
  term.attachCustomKeyEventHandler(function (e) {
    if (e.type === 'keydown' && e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
    }
    return true; // always let xterm.js process every key
  });

  new QWebChannel(qt.webChannelTransport, function (ch) {
    var bridge = ch.objects.bridge;

    bridge.write_data.connect(function (b64) {
      var bin = atob(b64);
      var buf = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      term.write(buf);
    });

    term.onData(function (data) {
      var enc = new TextEncoder().encode(data);
      var bin = '';
      enc.forEach(function (b) { bin += String.fromCharCode(b); });
      bridge.send_input(btoa(bin));
    });

    // term.onResize fires after every fit.fit() call — syncs PTY dimensions.
    term.onResize(function (sz) { bridge.resize_pty(sz.cols, sz.rows); });

    // Wait for fonts, then fit — also sends resize_pty then js_ready (in doFit).
    document.fonts.ready.then(function () {
      requestAnimationFrame(function () { requestAnimationFrame(function () { doFit(bridge); }); });
    });
  });
}());
</script>
</body>
</html>
"""


class _ClaudeProcess(QObject):
    """Runs `claude` in a POSIX PTY and streams base64-encoded output."""

    output_b64 = Signal(str)
    finished = Signal()

    _MAX_BUFFER_CHUNKS = 250  # ~1 MB max per session at 4 KB chunks

    def __init__(self) -> None:
        super().__init__()
        self._master_fd: int | None = None
        self._process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._cols = 80
        self._rows = 24
        self._pty_cols = 0  # tracks actual PTY size to avoid duplicate SIGWINCH
        self._pty_rows = 0
        self._output_buffer: list[bytes] = []

    def start(self, cwd: Path, extra_dirs: list[Path], session_id: str | None = None) -> None:
        if self.is_running():
            return

        claude = shutil.which("claude")
        if not claude:
            self._emit_msg(
                "\r\n\x1b[31mClaude Code CLI not found on PATH.\x1b[0m\r\n"
                "Install it from \x1b]8;;https://claude.ai/code\x1b\\claude.ai/code"
                "\x1b]8;;\x1b\\\r\n"
            )
            return

        if platform.system() == "Windows":
            self._emit_msg("\r\n[Windows PTY not supported yet]\r\n")
            return

        args = [claude]
        if session_id:
            args += ["--session-id", session_id]
        for d in extra_dirs:
            args += ["--add-dir", str(d)]

        try:
            import pty

            master_fd, slave_fd = pty.openpty()
        except (ImportError, OSError) as exc:
            self._emit_msg(f"\r\n\x1b[31mPTY unavailable: {exc}\x1b[0m\r\n")
            return

        self._master_fd = master_fd
        self._stop.clear()

        # Explicit terminal environment so Claude uses full 24-bit color and
        # renders its interactive picker/selection highlights correctly.
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env.pop("NO_COLOR", None)
        env.pop("FORCE_NO_COLOR", None)

        try:
            self._process = subprocess.Popen(
                args,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=str(cwd),
                env=env,
                close_fds=True,
            )
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            self._master_fd = None
            self._emit_msg(f"\r\n\x1b[31mFailed to launch claude: {exc}\x1b[0m\r\n")
            return

        os.close(slave_fd)
        self.resize(self._cols, self._rows)
        self._reader = threading.Thread(
            target=self._read_loop, daemon=True, name="claude-pty"
        )
        self._reader.start()

    def stop(self) -> None:
        self._stop.set()
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        self._close_fd()

    def write_bytes(self, data: bytes) -> None:
        fd = self._master_fd
        if fd is not None:
            try:
                os.write(fd, data)
            except OSError:
                pass

    def resize(self, cols: int, rows: int) -> None:
        self._cols = max(1, cols)
        self._rows = max(1, rows)
        fd = self._master_fd
        if fd is None or cols <= 0 or rows <= 0:
            return
        if self._cols == self._pty_cols and self._rows == self._pty_rows:
            return  # PTY already at this size — skip SIGWINCH to avoid double-render
        try:
            import fcntl
            import struct
            import termios

            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", self._rows, self._cols, 0, 0))
            self._pty_cols = self._cols
            self._pty_rows = self._rows
        except (OSError, ImportError):
            pass

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def replay(self, write_fn) -> None:
        """Feed every buffered output chunk into write_fn(b64_str).

        Call AFTER connecting output_b64 so that new chunks from the reader
        thread arrive via signal (queued, processed after this returns) while
        the buffer covers everything up to this moment — no gap, no dup.
        """
        for chunk in list(self._output_buffer):
            write_fn(base64.b64encode(chunk).decode("ascii"))

    def _emit_msg(self, text: str) -> None:
        data = text.encode()
        self._append_buffer(data)
        self.output_b64.emit(base64.b64encode(data).decode("ascii"))

    def _append_buffer(self, chunk: bytes) -> None:
        if len(self._output_buffer) >= self._MAX_BUFFER_CHUNKS:
            del self._output_buffer[: len(self._output_buffer) - self._MAX_BUFFER_CHUNKS + 1]
        self._output_buffer.append(chunk)

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            fd = self._master_fd
            if fd is None:
                break
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            self._append_buffer(chunk)
            self.output_b64.emit(base64.b64encode(chunk).decode("ascii"))
        self._close_fd()
        self.finished.emit()

    def _close_fd(self) -> None:
        fd, self._master_fd = self._master_fd, None
        self._pty_cols = 0
        self._pty_rows = 0
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


class _TerminalBridge(QObject):
    """QWebChannel object exposed to xterm.js as `bridge`."""

    write_data = Signal(str)  # base64 bytes → xterm.write()
    ready = Signal()           # fires once after first doFit sets correct size

    def __init__(self, process: _ClaudeProcess) -> None:
        super().__init__()
        self._process = process
        self._cols = 80
        self._rows = 24

    def set_process(self, process: _ClaudeProcess) -> None:
        """Swap the active process (e.g. when switching session directories)."""
        self._process = process
        process.resize(self._cols, self._rows)

    @Slot(str)
    def send_input(self, b64: str) -> None:
        self._process.write_bytes(base64.b64decode(b64))

    @Slot(int, int)
    def resize_pty(self, cols: int, rows: int) -> None:
        self._cols = cols
        self._rows = rows
        self._process.resize(cols, rows)

    @Slot()
    def js_ready(self) -> None:
        self.ready.emit()


class ClaudeSessionCache(QObject):
    """Shared cache of running _ClaudeProcess instances keyed by directory.

    One cache is created in MainWindow and shared across both pane views so
    returning to a previously-opened directory resumes the same CC session.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sessions: dict[Path, _ClaudeProcess] = {}
        self._extras: dict[Path, list[Path]] = {}

    def get_or_create(self, cwd: Path, extra_dirs: list[Path]) -> _ClaudeProcess:
        key = cwd.resolve()
        if key in self._sessions:
            proc = self._sessions[key]
            if proc.is_running():
                return proc
        proc = _ClaudeProcess()
        self._sessions[key] = proc
        self._extras[key] = extra_dirs
        proc.finished.connect(lambda k=key: self._sessions.pop(k, None))
        proc.start(cwd, extra_dirs, session_id=_session_id_for(key))
        return proc

    def force_restart(self, cwd: Path, extra_dirs: list[Path]) -> _ClaudeProcess:
        """Start a brand-new CC session, ignoring any saved session ID."""
        key = cwd.resolve()
        old = self._sessions.pop(key, None)
        if old is not None:
            old.stop()
        proc = _ClaudeProcess()
        self._sessions[key] = proc
        self._extras[key] = extra_dirs
        proc.finished.connect(lambda k=key: self._sessions.pop(k, None))
        proc.start(cwd, extra_dirs)  # no session_id → CC picks a fresh UUID
        return proc

    def stop_all(self) -> None:
        for proc in list(self._sessions.values()):
            proc.stop()
        self._sessions.clear()
        self._extras.clear()


class ClaudeTerminalWidget(QFrame):
    """Claude Code CLI embedded in a PaneView's content_stack, like QuickViewWidget.

    Call show_for(cwd, extra_dirs) each time the widget is made visible.
    Sessions are cached by directory — returning to the same dir resumes
    the existing CC process (display resets but conversation continues).
    """

    def __init__(self, session_cache: ClaudeSessionCache, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("claudeTerminalWidget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._cache = session_cache
        self._current_cwd: Path | None = None
        self._current_extra: list[Path] = []
        self._current_process: _ClaudeProcess | None = None
        self._pending_proc: _ClaudeProcess | None = None  # waiting for js_ready after setHtml
        self._js_ready = False

        self._cwd_label = QLabel("")
        self._cwd_label.setObjectName("claudeTerminalCwd")
        self._cwd_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        new_btn = QPushButton("New Session")
        new_btn.setObjectName("secondaryActionButton")
        new_btn.clicked.connect(self._restart)

        header = QHBoxLayout()
        header.setContentsMargins(8, 4, 8, 4)
        header.setSpacing(8)
        header.addWidget(self._cwd_label, 1)
        header.addWidget(new_btn)

        header_widget = QWidget()
        header_widget.setObjectName("claudeTerminalHeader")
        header_widget.setLayout(header)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header_widget)

        if _WEB_AVAILABLE:
            self._stub_process = _ClaudeProcess()  # never started; bridge needs a target
            self._bridge = _TerminalBridge(self._stub_process)
            self._bridge.ready.connect(self._on_js_ready)

            channel = QWebChannel(self)
            channel.registerObject("bridge", self._bridge)

            self._view = QWebEngineView()
            self._view.page().setWebChannel(channel)
            self._view.setHtml(_XTERM_HTML)
            layout.addWidget(self._view, 1)
        else:
            note = QLabel(
                "Embedded terminal needs PySide6-WebEngine.\n"
                "Install: pip install PySide6-WebEngine"
            )
            note.setObjectName("aiPaneStatus")
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(note, 1)

    def show_for(self, cwd: Path, extra_dirs: list[Path]) -> None:
        """Switch to the CC session for cwd.

        Always reloads the xterm.js page for a guaranteed clean slate, then
        replays the session's output buffer so history is always visible.
        This handles both "new session" and "returning to a previous session"
        identically — no stale content, no lost history.
        """
        self._cwd_label.setText(str(cwd))
        self._current_cwd = cwd
        self._current_extra = extra_dirs

        if self._current_process is not None:
            try:
                self._current_process.output_b64.disconnect(self._bridge.write_data)
            except RuntimeError:
                pass
            self._current_process = None

        if not _WEB_AVAILABLE:
            return

        proc = self._cache.get_or_create(cwd, extra_dirs)
        self._bridge.set_process(proc)  # resize/input wired before page reload
        self._pending_proc = proc
        self._js_ready = False
        self._view.setHtml(_XTERM_HTML)

    def stop_session(self) -> None:
        if self._current_process is not None:
            try:
                self._current_process.output_b64.disconnect(self._bridge.write_data)
            except RuntimeError:
                pass
            self._current_process = None
        self._pending_proc = None
        self._js_ready = False

    def _on_js_ready(self) -> None:
        self._js_ready = True
        if self._pending_proc is not None:
            proc, self._pending_proc = self._pending_proc, None
            self._current_process = proc
            # Connect live output first, then replay buffer.
            # Reader-thread signals are queued in Qt's event loop and won't be
            # delivered until after this method returns, so replay[0..N] arrives
            # before live[N+1..] — clean ordering, no duplicates.
            proc.output_b64.connect(self._bridge.write_data)
            proc.replay(self._bridge.write_data.emit)
            self._view.setFocus()

    def _restart(self) -> None:
        if self._current_cwd is None:
            return
        if self._current_process is not None:
            try:
                self._current_process.output_b64.disconnect(self._bridge.write_data)
            except RuntimeError:
                pass
            self._current_process = None
        cwd = self._current_cwd
        proc = self._cache.force_restart(cwd, self._current_extra)
        self._bridge.set_process(proc)
        if _WEB_AVAILABLE:
            self._pending_proc = proc
            self._js_ready = False
            self._view.setHtml(_XTERM_HTML)
        else:
            self._current_process = proc
            proc.output_b64.connect(self._bridge.write_data)
