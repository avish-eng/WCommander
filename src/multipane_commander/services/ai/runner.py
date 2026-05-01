from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from claude_agent_sdk import query as default_query
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from multipane_commander.config.model import AiConfig
from multipane_commander.services.ai.availability import detect_claude_cli
from multipane_commander.services.ai.events import (
    AiError,
    AiResult,
    TextChunk,
    ToolCallEnd,
    ToolCallStart,
)
from multipane_commander.services.ai.sandbox import PaneRoots

log = logging.getLogger(__name__)


class AiUnavailable(RuntimeError):
    """Raised when start_session is called but AI features can't run.

    Reasons: AiConfig.enabled is False, or the Claude Code CLI isn't
    installed/found on PATH. Callers should catch this and present a
    user-facing message; never let it crash the app.
    """


# SDK message types we translate. Anything else (StreamEvent, RateLimitEvent,
# SystemMessage, UserMessage) we currently drop — feature specs can lift any
# they need.
_AssistantOrResult = AssistantMessage | ResultMessage

QueryFn = Callable[..., AsyncIterator[Any]]


class _AgentWorker(QObject):
    """Runs one agent session on a dedicated QThread.

    Mirrors `_FileJobWorker` from services/jobs/manager.py: signals across
    threads via a bridge, cancellation via a flag checked between SDK
    messages, errors caught and re-emitted instead of crashing the thread.
    """

    event = Signal(object)  # AiEvent
    finished = Signal(object)  # AiResult

    def __init__(
        self,
        *,
        session_id: str,
        prompt: str,
        options: ClaudeAgentOptions,
        query_fn: QueryFn,
    ) -> None:
        super().__init__()
        self._session_id = session_id
        self._prompt = prompt
        self._options = options
        self._query_fn = query_fn
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        log.debug("worker thread started: session=%s", self._session_id)
        try:
            asyncio.run(self._drive())
        except Exception as exc:  # noqa: BLE001
            log.exception("asyncio.run blew up for session=%s", self._session_id)
            self.finished.emit(
                AiResult(
                    session_id=self._session_id,
                    status="error",
                    text="",
                    tool_calls=0,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
        log.debug("worker thread exiting: session=%s", self._session_id)

    async def _drive(self) -> None:
        log.debug("_drive started: session=%s prompt=%.80r", self._session_id, self._prompt)
        text_parts: list[str] = []
        tool_call_count = 0
        usage: dict | None = None
        cost_usd: float | None = None
        status: str = "completed"
        error: str | None = None

        try:
            agen = self._query_fn(prompt=self._prompt, options=self._options)
            log.debug("query iterator created, entering message loop")
            async for message in agen:
                log.debug("sdk message: %s", type(message).__name__)
                if self._cancel.is_set():
                    log.debug("cancel requested — breaking loop")
                    status = "cancelled"
                    try:
                        await agen.aclose()  # type: ignore[union-attr]
                    except Exception:  # noqa: BLE001
                        pass
                    break

                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            self.event.emit(
                                TextChunk(session_id=self._session_id, text=block.text)
                            )
                            text_parts.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            tool_call_count += 1
                            log.debug("tool call: %s input=%r", block.name, block.input)
                            self.event.emit(
                                ToolCallStart(
                                    session_id=self._session_id,
                                    tool_use_id=block.id,
                                    name=block.name,
                                    input=dict(block.input),
                                )
                            )
                        elif isinstance(block, ToolResultBlock):
                            log.debug("tool result: id=%s is_error=%s", block.tool_use_id, block.is_error)
                            self.event.emit(
                                ToolCallEnd(
                                    session_id=self._session_id,
                                    tool_use_id=block.tool_use_id,
                                    name="",
                                    ok=not bool(block.is_error),
                                )
                            )
                elif isinstance(message, ResultMessage):
                    log.debug(
                        "ResultMessage: is_error=%s turns=%s cost=$%.5f",
                        message.is_error, message.num_turns, message.total_cost_usd or 0,
                    )
                    usage = message.usage
                    cost_usd = message.total_cost_usd
                    if message.is_error:
                        status = "error"
                        error = message.result or "Agent reported an error"
                else:
                    log.debug("ignored sdk message type: %s", type(message).__name__)
        except Exception as exc:  # noqa: BLE001
            log.exception("exception in _drive session=%s", self._session_id)
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
            self.event.emit(
                AiError(session_id=self._session_id, message=error)
            )

        log.debug(
            "_drive done: session=%s status=%s tools=%d text_len=%d",
            self._session_id, status, tool_call_count, sum(len(t) for t in text_parts),
        )
        self.finished.emit(
            AiResult(
                session_id=self._session_id,
                status=status,  # type: ignore[arg-type]
                text="".join(text_parts),
                tool_calls=tool_call_count,
                error=error,
                usage=usage,
                cost_usd=cost_usd,
            )
        )


class _AgentEventBridge(QObject):
    """Marshals worker signals back to the GUI thread.

    Mirrors `_JobEventBridge` from services/jobs/manager.py. The bridge is
    constructed on the GUI thread and uses `@Slot` forwarders so that signals
    crossing the thread boundary are queued and delivered on the GUI thread.
    """

    event_marshaled = Signal(object)
    finished_marshaled = Signal(object)

    @Slot(object)
    def forward_event(self, ev: object) -> None:
        self.event_marshaled.emit(ev)

    @Slot(object)
    def forward_finished(self, result: object) -> None:
        self.finished_marshaled.emit(result)


class AgentRunner(QObject):
    """Service-layer entry point for running Claude agent sessions.

    Lifecycle and threading match `JobManager`: one QThread per session,
    cleanup on `thread.finished`, signal payloads delivered as `Signal(object)`
    with the session_id baked into the event itself.
    """

    event = Signal(object)  # AiEvent
    session_done = Signal(object)  # AiResult

    def __init__(
        self,
        config: AiConfig,
        *,
        query_fn: QueryFn | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._query_fn = query_fn or default_query
        self._threads: list[QThread] = []
        self._workers: dict[str, _AgentWorker] = {}
        self._bridges: dict[str, _AgentEventBridge] = {}

    @property
    def config(self) -> AiConfig:
        return self._config

    def start_session(
        self,
        *,
        prompt: str,
        system_prompt: str,
        allowed_tools: list[str],
        pane_roots: PaneRoots,
    ) -> str:
        """Start a new session and return its id.

        Raises AiUnavailable if the runner cannot serve a session right now.
        """
        if not self._config.enabled:
            raise AiUnavailable("AI features are disabled in config.")
        cli_status = detect_claude_cli()
        if not cli_status.available:
            raise AiUnavailable(cli_status.reason or "Claude Code CLI unavailable.")

        session_id = uuid.uuid4().hex
        log.info(
            "start_session: id=%s tools=%s cwd=%s prompt=%.80r",
            session_id, allowed_tools, pane_roots.left, prompt,
        )

        def _sdk_stderr(line: str) -> None:
            log.debug("[claude-cli stderr] %s", line.rstrip())

        # Force the system CLI so the bundled one (which times out inside
        # a QThread due to Qt's signal/fd setup) is never selected.
        import shutil as _shutil
        system_cli = _shutil.which("claude")
        log.debug("system claude CLI: %s", system_cli)

        # Use a neutral cwd (/tmp) to avoid slow CLI startup when a pane root
        # is the home directory — ~3k session files in ~/.claude/ cause a 60s
        # initialize timeout. Access to pane directories is granted via --add-dir.
        import tempfile as _tempfile
        neutral_cwd = _tempfile.gettempdir()
        log.debug("agent cwd: %s (pane_roots: left=%s right=%s)", neutral_cwd, pane_roots.left, pane_roots.right)

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=list(allowed_tools),
            permission_mode="dontAsk",
            cwd=neutral_cwd,
            add_dirs=[str(pane_roots.left), str(pane_roots.right)],
            model=self._config.model or None,
            stderr=_sdk_stderr,
            cli_path=system_cli,
        )

        worker = _AgentWorker(
            session_id=session_id,
            prompt=prompt,
            options=options,
            query_fn=self._query_fn,
        )
        thread = QThread(self)
        bridge = _AgentEventBridge(self)
        worker.moveToThread(thread)
        self._workers[session_id] = worker
        self._bridges[session_id] = bridge
        self._threads.append(thread)

        # Worker -> bridge (queued across threads), bridge -> AgentRunner (direct, GUI thread)
        worker.event.connect(bridge.forward_event, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(
            bridge.forward_finished, Qt.ConnectionType.QueuedConnection
        )
        bridge.event_marshaled.connect(self.event)
        bridge.finished_marshaled.connect(self._on_finished)
        thread.started.connect(worker.run)

        def cleanup() -> None:
            log.debug("cleanup: session=%s", session_id)
            worker.deleteLater()
            bridge.deleteLater()
            thread.deleteLater()
            if thread in self._threads:
                self._threads.remove(thread)
            self._workers.pop(session_id, None)
            self._bridges.pop(session_id, None)

        thread.finished.connect(cleanup)
        log.debug("starting QThread for session=%s", session_id)
        thread.start()
        return session_id

    def cancel(self, session_id: str) -> None:
        log.info("cancel requested: session=%s", session_id)
        worker = self._workers.get(session_id)
        if worker is not None:
            worker.cancel()

    @Slot(object)
    def _on_finished(self, result: object) -> None:
        if isinstance(result, AiResult):
            log.info(
                "session finished: id=%s status=%s tools=%d cost=$%.5f error=%r",
                result.session_id, result.status, result.tool_calls,
                result.cost_usd or 0, result.error,
            )
        self.session_done.emit(result)
        if isinstance(result, AiResult):
            for sid, worker in list(self._workers.items()):
                if sid == result.session_id and worker.thread() is not None:
                    worker.thread().quit()
                    break
