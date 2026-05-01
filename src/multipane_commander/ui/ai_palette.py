from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    _WEB_ENGINE_AVAILABLE = True
except ImportError:  # pragma: no cover
    QWebEngineView = None  # type: ignore[assignment, misc]
    _WEB_ENGINE_AVAILABLE = False


_PALETTE_SYSTEM_PROMPT = (
    "You are an AI assistant embedded in a dual-pane file manager. "
    "The user has two directory panes open. "
    "You have access to Read, Glob, and Grep tools to inspect files in those directories. "
    "Answer the user's question concisely using Markdown. "
    "Use headers, bullet points, and inline code where helpful. "
    "If you need to look at files, do so; otherwise answer directly."
)

_HTML_TEMPLATE = """\
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{background:#1e1e1e;color:#d4d4d4;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:13px;line-height:1.65;padding:14px 18px;margin:0}}
h1,h2,h3{{color:#c8d0e0;margin-top:1.1em;margin-bottom:.3em}}
h1{{font-size:1.2em}}h2{{font-size:1.1em}}h3{{font-size:1em}}
code{{background:#2a2d2e;padding:.1em .35em;border-radius:3px;
  font-family:"SF Mono",Menlo,monospace;font-size:.9em}}
pre{{background:#2a2d2e;padding:10px 12px;border-radius:4px;overflow-x:auto}}
pre code{{background:none;padding:0}}
ul,ol{{padding-left:1.4em;margin:.4em 0}}
li{{margin:.2em 0}}
a{{color:#4ec9b0}}
blockquote{{border-left:3px solid #4ec9b0;margin:0;padding-left:12px;color:#9da5b4}}
hr{{border:none;border-top:1px solid #3a3a3a;margin:.8em 0}}
p{{margin:.5em 0}}
</style></head><body>{body}</body></html>"""


def _markdown_to_html(text: str) -> str:
    import mistune  # local import keeps startup fast

    return _HTML_TEMPLATE.format(body=mistune.html(text))


class AiPaletteDialog(QDialog):
    """Floating Ctrl+K command palette — natural-language queries streamed via Claude."""

    def __init__(
        self,
        runner: AgentRunner,
        pane_roots: PaneRoots,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self.setObjectName("aiPalette")
        self.setWindowTitle("AI Palette")
        self.setMinimumWidth(680)
        self.resize(720, 520)

        self._runner = runner
        self._pane_roots = pane_roots
        self._session_id: str | None = None
        self._text_chunks: list[str] = []
        self._rendered_view: "QWebEngineView | None" = None

        self._input = QLineEdit()
        self._input.setObjectName("aiPaletteInput")
        self._input.setPlaceholderText("Ask Claude about your files… (Enter to send)")
        self._input.returnPressed.connect(self._send)

        self._status = QLabel("")
        self._status.setObjectName("aiPaletteStatus")

        self._spinner = QProgressBar()
        self._spinner.setObjectName("aiPaletteSpinner")
        self._spinner.setRange(0, 0)
        self._spinner.setTextVisible(False)
        self._spinner.setMaximumHeight(4)
        self._spinner.setVisible(False)

        self._text_view = QPlainTextEdit()
        self._text_view.setObjectName("aiPaletteText")
        self._text_view.setReadOnly(True)

        self._output_stack = QStackedWidget()
        self._output_stack.addWidget(self._text_view)  # index 0

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("aiPaletteCancel")
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._cancel)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("aiPaletteSend")
        self._send_btn.clicked.connect(self._send)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._send_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._input)
        layout.addWidget(self._status)
        layout.addWidget(self._spinner)
        layout.addWidget(self._output_stack, 1)
        layout.addLayout(btn_row)

        runner.event.connect(self._on_event)
        runner.session_done.connect(self._on_done)

    def update_context(self, pane_roots: PaneRoots) -> None:
        """Refresh the pane roots when the user navigates in either pane."""
        self._pane_roots = pane_roots

    def show_and_focus(self) -> None:
        self.show()
        self.raise_()
        self._input.setFocus()
        self._input.selectAll()

    def _send(self) -> None:
        prompt = self._input.text().strip()
        if not prompt:
            return
        if self._session_id is not None:
            self._runner.cancel(self._session_id)
            self._session_id = None
        self._text_chunks = []
        self._text_view.clear()
        self._output_stack.setCurrentIndex(0)
        self._status.setText("Thinking…")
        self._spinner.setVisible(True)
        self._cancel_btn.setVisible(True)
        self._send_btn.setEnabled(False)
        try:
            self._session_id = self._runner.start_session(
                prompt=prompt,
                system_prompt=_PALETTE_SYSTEM_PROMPT,
                allowed_tools=["Read", "Glob", "Grep"],
                pane_roots=self._pane_roots,
            )
        except AiUnavailable as exc:
            self._status.setText(f"Error: {exc}")
            self._spinner.setVisible(False)
            self._cancel_btn.setVisible(False)
            self._send_btn.setEnabled(True)

    def _cancel(self) -> None:
        if self._session_id is not None:
            self._runner.cancel(self._session_id)

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
            self._cancel_btn.setVisible(False)
            self._send_btn.setEnabled(True)
            self._session_id = None

    def _on_done(self, result: object) -> None:
        if not isinstance(result, AiResult):
            return
        if result.session_id != self._session_id:
            return
        self._session_id = None
        self._spinner.setVisible(False)
        self._cancel_btn.setVisible(False)
        self._send_btn.setEnabled(True)
        if result.status == "completed":
            self._render_markdown("".join(self._text_chunks))
            self._status.setText("Done")
        elif result.status == "cancelled":
            self._status.setText("Cancelled.")
        else:
            self._status.setText(f"Error: {result.error or 'failed'}")

    def _render_markdown(self, text: str) -> None:
        if _WEB_ENGINE_AVAILABLE:
            if self._rendered_view is None:
                assert QWebEngineView is not None
                view = QWebEngineView()
                view.setObjectName("aiPaletteRendered")
                self._output_stack.addWidget(view)
                self._rendered_view = view
            self._rendered_view.setHtml(_markdown_to_html(text))
            self._output_stack.setCurrentWidget(self._rendered_view)
        else:
            self._text_view.setPlainText(text)
            self._output_stack.setCurrentIndex(0)

    def accept(self) -> None:
        pass  # prevent QDialog from closing when Enter is pressed

    def reject(self) -> None:
        # Called by Escape — cancel any in-flight session and hide
        if self._session_id is not None:
            self._runner.cancel(self._session_id)
            self._session_id = None
        self.hide()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._session_id is not None:
            self._runner.cancel(self._session_id)
            self._session_id = None
        super().closeEvent(event)
