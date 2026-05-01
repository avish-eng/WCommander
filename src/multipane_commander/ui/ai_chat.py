from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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


_CHAT_SYSTEM_PROMPT = (
    "You are an AI assistant embedded in a dual-pane file manager. "
    "You have access to Read, Glob, and Grep tools to inspect files in the user's directories. "
    "Answer concisely and helpfully using Markdown. "
    "Use headers, bullet points, and inline code where they help readability."
)


def _build_history_prompt(history: list[tuple[str, str]], current: str) -> str:
    """Build a prompt that prepends conversation history for pseudo-multi-turn context."""
    if not history:
        return current
    lines = ["Previous conversation:"]
    for user_msg, assistant_msg in history:
        lines.append(f"User: {user_msg}")
        lines.append(f"Assistant: {assistant_msg}")
        lines.append("")
    lines.append(f"Current question: {current}")
    return "\n".join(lines)


class _ChatBubble(QFrame):
    """A single message bubble showing role label + plain-text body."""

    def __init__(self, text: str, role: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatBubble")
        self.setProperty("role", role)

        role_label = QLabel(role.upper())
        role_label.setObjectName("chatBubbleRole")

        self._body = QPlainTextEdit()
        self._body.setObjectName("chatBubbleBody")
        self._body.setReadOnly(True)
        self._body.setPlainText(text)
        self._body.setMaximumHeight(280)
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        layout.addWidget(role_label)
        layout.addWidget(self._body)

    def set_text(self, text: str) -> None:
        self._body.setPlainText(text)


class AiChatWidget(QFrame):
    """Multi-turn AI chat panel.

    Conversation history is prepended to each new prompt so Claude has context.
    Ctrl+Enter sends the current input; Clear resets history.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aiChat")

        self._runner: AgentRunner | None = None
        self._pane_roots: PaneRoots | None = None
        self._session_id: str | None = None
        self._history: list[tuple[str, str]] = []  # (user_msg, assistant_msg)
        self._current_user_msg: str = ""
        self._text_chunks: list[str] = []
        self._current_bubble: _ChatBubble | None = None

        title = QLabel("AI Chat")
        title.setObjectName("aiChatTitle")

        self._status = QLabel("")
        self._status.setObjectName("aiChatStatus")

        self._spinner = QProgressBar()
        self._spinner.setObjectName("aiChatSpinner")
        self._spinner.setRange(0, 0)
        self._spinner.setTextVisible(False)
        self._spinner.setMaximumHeight(3)
        self._spinner.setVisible(False)

        # Scrollable message area
        self._messages_widget = QWidget()
        self._messages_widget.setObjectName("aiChatMessages")
        self._messages_layout = QVBoxLayout(self._messages_widget)
        self._messages_layout.setContentsMargins(0, 0, 0, 0)
        self._messages_layout.setSpacing(4)
        self._messages_layout.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("aiChatScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._messages_widget)

        self._input = QPlainTextEdit()
        self._input.setObjectName("aiChatInput")
        self._input.setPlaceholderText("Type your message… (Ctrl+Enter to send)")
        self._input.setMaximumHeight(80)
        self._input.installEventFilter(self)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("aiChatSend")
        self._send_btn.clicked.connect(self._send)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setObjectName("aiChatClear")
        self._clear_btn.clicked.connect(self._clear)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._send_btn)

        hdr = QHBoxLayout()
        hdr.addWidget(title)
        hdr.addWidget(self._status)
        hdr.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        layout.addLayout(hdr)
        layout.addWidget(self._spinner)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._input)
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

    def update_pane_roots(self, pane_roots: PaneRoots | None) -> None:
        self._pane_roots = pane_roots

    def eventFilter(self, obj: object, event: object) -> bool:
        if obj is self._input and isinstance(event, QKeyEvent):
            if event.type() == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            ):
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._send()
                    return True
        return super().eventFilter(obj, event)

    def _send(self) -> None:
        prompt = self._input.toPlainText().strip()
        if not prompt:
            return
        if self._runner is None or self._pane_roots is None:
            self._status.setText("AI runtime unavailable.")
            return
        if self._session_id is not None:
            self._runner.cancel(self._session_id)
            self._session_id = None
        self._current_user_msg = prompt
        self._text_chunks = []
        self._input.clear()

        user_bubble = _ChatBubble(prompt, "user")
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, user_bubble)
        self._current_bubble = _ChatBubble("", "assistant")
        self._messages_layout.insertWidget(
            self._messages_layout.count() - 1, self._current_bubble
        )
        self._scroll_to_bottom()
        self._status.setText("Thinking…")
        self._spinner.setVisible(True)
        self._send_btn.setEnabled(False)

        full_prompt = _build_history_prompt(self._history, prompt)
        try:
            self._session_id = self._runner.start_session(
                prompt=full_prompt,
                system_prompt=_CHAT_SYSTEM_PROMPT,
                allowed_tools=["Read", "Glob", "Grep"],
                pane_roots=self._pane_roots,
            )
        except AiUnavailable as exc:
            self._status.setText(f"Error: {exc}")
            self._spinner.setVisible(False)
            self._send_btn.setEnabled(True)
            self._session_id = None

    def _clear(self) -> None:
        if self._session_id is not None and self._runner is not None:
            self._runner.cancel(self._session_id)
            self._session_id = None
        self._history = []
        self._text_chunks = []
        self._current_bubble = None
        self._status.setText("")
        self._spinner.setVisible(False)
        self._send_btn.setEnabled(True)
        # Remove all bubble widgets (everything except the trailing stretch)
        while self._messages_layout.count() > 1:
            item = self._messages_layout.itemAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()
            self._messages_layout.removeItem(item)

    def _scroll_to_bottom(self) -> None:
        vsb = self._scroll.verticalScrollBar()
        vsb.setValue(vsb.maximum())

    def _on_event(self, event: object) -> None:
        sid = getattr(event, "session_id", None)
        if sid != self._session_id:
            return
        if isinstance(event, TextChunk):
            self._text_chunks.append(event.text)
            if self._current_bubble is not None:
                self._current_bubble.set_text("".join(self._text_chunks))
            self._scroll_to_bottom()
        elif isinstance(event, ToolCallStart):
            self._status.setText(f"{event.name}…")
        elif isinstance(event, AiError):
            self._status.setText(f"Error: {event.message}")
            self._spinner.setVisible(False)
            self._send_btn.setEnabled(True)
            self._session_id = None

    def _on_done(self, result: object) -> None:
        if not isinstance(result, AiResult):
            return
        if result.session_id != self._session_id:
            return
        self._session_id = None
        self._spinner.setVisible(False)
        self._send_btn.setEnabled(True)
        if result.status == "completed":
            assistant_text = "".join(self._text_chunks)
            self._history.append((self._current_user_msg, assistant_text))
            self._status.setText(f"Turn {len(self._history)}")
        elif result.status == "cancelled":
            self._status.setText("Cancelled.")
        else:
            self._status.setText(f"Error: {result.error or 'failed'}")
