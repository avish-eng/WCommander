from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from multipane_commander.services.ai import (
    AgentRunner,
    AiError,
    AiResult,
    AiUnavailable,
    PaneRoots,
    TextChunk,
    ToolCallStart,
)
from multipane_commander.services.ai.cache import load_summary, save_summary

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    _WEB_ENGINE_AVAILABLE = True
except ImportError:  # pragma: no cover
    QWebEngineView = None  # type: ignore[assignment, misc]
    _WEB_ENGINE_AVAILABLE = False


_AI_PANE_SYSTEM_PROMPT = (
    "You are inspecting a file in a file manager's AI context pane. "
    "Use the Read tool to view the file at the path the user gives you, "
    "then write a concise summary of what it is and what it contains using Markdown. "
    "For code: say what the module/script does and list key functions/classes. "
    "For data files: describe the shape and notable columns. "
    "For documents: give the gist with key points as bullets. "
    "Don't quote the file verbatim. Don't apologize. "
    "If the file is empty, unreadable, or denied by the sandbox, say so plainly."
)

_HTML_TEMPLATE = """\
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{background:#1e1e1e;color:#d4d4d4;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:12px;line-height:1.6;padding:12px 14px;margin:0}}
h1,h2,h3{{color:#c8d0e0;margin-top:1em;margin-bottom:.3em}}
h1{{font-size:1.1em}}h2{{font-size:1.05em}}h3{{font-size:1em}}
code{{background:#2a2d2e;padding:.1em .3em;border-radius:3px;
  font-family:"SF Mono",Menlo,monospace;font-size:.85em}}
pre{{background:#2a2d2e;padding:8px 10px;border-radius:4px;overflow-x:auto}}
pre code{{background:none;padding:0}}
ul,ol{{padding-left:1.3em;margin:.3em 0}}
li{{margin:.15em 0}}
a{{color:#4ec9b0}}
blockquote{{border-left:3px solid #4ec9b0;margin:0;padding-left:10px;color:#9da5b4}}
p{{margin:.4em 0}}
</style></head><body>{body}</body></html>"""


def _markdown_to_html(text: str) -> str:
    import mistune  # local import keeps startup fast

    return _HTML_TEMPLATE.format(body=mistune.html(text))


_SKIP_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".ico", ".heic",
    ".pdf", ".svg",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".aiff",
    ".zip", ".tar", ".7z", ".rar", ".jar", ".gz", ".bz2", ".xz",
})
_ARCHIVE_COMPOUND = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz")


def _is_summarizable(path: Path) -> bool:
    if path.suffix.lower() in _SKIP_SUFFIXES:
        return False
    name = path.name.lower()
    if any(name.endswith(s) for s in _ARCHIVE_COMPOUND):
        return False
    try:
        with path.open("rb") as fh:
            return b"\x00" not in fh.read(4096)
    except OSError:
        return False


class AiPane(QFrame):
    """Persistent third-column AI context pane.

    Call set_path() whenever the active pane's focused file changes.
    Auto-starts a summary session (with cache hit fast-path), shows a spinner
    while in-flight, and renders markdown when done.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aiPane")
        self.setMinimumWidth(180)

        self._runner: AgentRunner | None = None
        self._pane_roots: PaneRoots | None = None
        self._current_path: Path | None = None
        self._session_id: str | None = None
        self._text_chunks: list[str] = []
        self._rendered_view: "QWebEngineView | None" = None

        title_label = QLabel("AI Context")
        title_label.setObjectName("aiPaneTitle")

        self._status = QLabel("Navigate to a file to see its AI summary.")
        self._status.setObjectName("aiPaneStatus")
        self._status.setWordWrap(True)

        self._spinner = QProgressBar()
        self._spinner.setObjectName("aiPaneSpinner")
        self._spinner.setRange(0, 0)
        self._spinner.setTextVisible(False)
        self._spinner.setMaximumHeight(4)
        self._spinner.setVisible(False)

        self._text_view = QPlainTextEdit()
        self._text_view.setObjectName("aiPaneText")
        self._text_view.setReadOnly(True)

        self._output_stack = QStackedWidget()
        self._output_stack.addWidget(self._text_view)  # index 0

        self._retry_btn = QPushButton("Retry")
        self._retry_btn.setObjectName("aiPaneRetry")
        self._retry_btn.setVisible(False)
        self._retry_btn.clicked.connect(self._retry)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self._retry_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.addWidget(title_label)
        layout.addWidget(self._status)
        layout.addWidget(self._spinner)
        layout.addWidget(self._output_stack, 1)
        layout.addLayout(btn_row)

    def set_runtime(
        self,
        runner: AgentRunner | None,
        pane_roots: PaneRoots | None,
    ) -> None:
        """Wire (or unwire) the AI runner. Called from main_window."""
        if self._runner is not None and self._runner is not runner:
            try:
                self._runner.event.disconnect(self._on_event)
            except (TypeError, RuntimeError):
                pass
            try:
                self._runner.session_done.disconnect(self._on_done)
            except (TypeError, RuntimeError):
                pass
        if runner is not None and runner is not self._runner:
            runner.event.connect(self._on_event)
            runner.session_done.connect(self._on_done)
        self._runner = runner
        self._pane_roots = pane_roots

    def set_path(self, path: Path | None) -> None:
        """Update the focused path. Cancels any in-flight session and starts fresh."""
        if path is not None and path == self._current_path:
            return
        self._current_path = path
        self._cancel_session()
        if path is None or path.is_dir() or not _is_summarizable(path):
            self._status.setText("No AI summary for this item.")
            self._spinner.setVisible(False)
            self._retry_btn.setVisible(False)
            self._text_view.clear()
            self._output_stack.setCurrentIndex(0)
            return
        self._start_summary()

    def _start_summary(self) -> None:
        if self._runner is None or self._pane_roots is None or self._current_path is None:
            self._status.setText("AI runtime unavailable.")
            return
        cached = load_summary(self._current_path)
        if cached is not None:
            self._render_markdown(cached)
            self._status.setText("Cached")
            self._spinner.setVisible(False)
            self._retry_btn.setVisible(True)
            return
        self._text_chunks = []
        self._text_view.clear()
        self._output_stack.setCurrentIndex(0)
        self._status.setText("Summarizing…")
        self._spinner.setVisible(True)
        self._retry_btn.setVisible(False)
        try:
            self._session_id = self._runner.start_session(
                prompt=str(self._current_path),
                system_prompt=_AI_PANE_SYSTEM_PROMPT,
                allowed_tools=["Read"],
                pane_roots=self._pane_roots,
            )
        except AiUnavailable as exc:
            self._status.setText(f"Error: {exc}")
            self._spinner.setVisible(False)
            self._retry_btn.setVisible(True)
            self._session_id = None

    def _retry(self) -> None:
        self._retry_btn.setVisible(False)
        self._start_summary()

    def _cancel_session(self) -> None:
        if self._session_id is not None and self._runner is not None:
            self._runner.cancel(self._session_id)
        self._session_id = None

    def _on_event(self, event: object) -> None:
        sid = getattr(event, "session_id", None)
        if sid != self._session_id:
            return
        if isinstance(event, TextChunk):
            self._text_chunks.append(event.text)
            self._text_view.setPlainText("".join(self._text_chunks))
            cursor = self._text_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._text_view.setTextCursor(cursor)
        elif isinstance(event, ToolCallStart):
            self._status.setText(f"{event.name}…")
        elif isinstance(event, AiError):
            self._status.setText(f"Error: {event.message}")
            self._spinner.setVisible(False)
            self._retry_btn.setVisible(True)
            self._session_id = None

    def _on_done(self, result: object) -> None:
        if not isinstance(result, AiResult):
            return
        if result.session_id != self._session_id:
            return
        self._session_id = None
        self._spinner.setVisible(False)
        self._retry_btn.setVisible(True)
        if result.status == "completed":
            text = "".join(self._text_chunks)
            if text and self._current_path is not None:
                save_summary(self._current_path, text)
            self._render_markdown(text)
            self._status.setText("Summary")
        elif result.status == "cancelled":
            self._status.setText("Cancelled.")
        else:
            self._status.setText(f"Error: {result.error or 'failed'}")

    def _render_markdown(self, text: str) -> None:
        if _WEB_ENGINE_AVAILABLE:
            if self._rendered_view is None:
                assert QWebEngineView is not None
                view = QWebEngineView()
                view.setObjectName("aiPaneRendered")
                self._output_stack.addWidget(view)
                self._rendered_view = view
            self._rendered_view.setHtml(_markdown_to_html(text))
            self._output_stack.setCurrentWidget(self._rendered_view)
        else:
            self._text_view.setPlainText(text)
            self._output_stack.setCurrentIndex(0)
