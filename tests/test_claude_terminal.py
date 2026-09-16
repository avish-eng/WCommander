import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget
import pytest
from multipane_commander.ui import claude_terminal as ct
from multipane_commander.ui.deep_terminal.surface import DeepTerminalSurface, build_deep_terminal_html


class Backend(QObject):
    output_received = Signal(bytes)
    started = Signal()
    exited = Signal(int)
    failed = Signal(str)

    def __init__(self, **kwargs):
        super().__init__()
        self.options = kwargs
        self.writes, self.sizes = [], []
        self.running = False
        self.stops = 0

    def start(self):
        self.running = True
        self.started.emit()

    def stop(self):
        self.stops += 1
        self.running = False

    def is_running(self):
        return self.running

    def write_bytes(self, data):
        self.writes.append(data)

    def resize(self, cols, rows):
        self.sizes.append((cols, rows))


@pytest.fixture
def app(monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ct.shutil, "which", lambda _: "claude")
    yield application
    application.processEvents()


def process_factory():
    return ct._ClaudeProcess(backend_factory=Backend)


def test_claude_uses_shared_backend_with_session_arguments(app, tmp_path):
    process = process_factory()
    process.resize(120, 40)
    process.start(tmp_path, [tmp_path / "extra"], session_id="session-123")
    options = process.backend.options
    assert options["shell"].program == "claude"
    assert options["shell"].args == ["--session-id", "session-123", "--add-dir", str(tmp_path / "extra")]
    assert options["initial_directory"] == tmp_path
    assert options["prefer_pty"] is True
    assert options["environment_overrides"]["TERM"] == "xterm-256color"
    assert process.backend.sizes == [(120, 40)]
    process.stop()


def test_claude_shares_raw_input_output_and_lifecycle(app, tmp_path):
    process = process_factory()
    process.start(tmp_path, [])
    output = []
    process.output_received.connect(output.append)
    process.backend.output_received.emit(b"hello \xf0\x9f")
    process.backend.output_received.emit(b"\x98\x80")
    replay = []
    process.replay(replay.append)
    assert replay == output == [b"hello \xf0\x9f", b"\x98\x80"]
    process.write_bytes(b"answer\r")
    assert process.backend.writes == [b"answer\r"]
    process.stop()
    assert process.backend.stops == 1


def test_late_old_session_exit_cannot_remove_replacement(app, tmp_path):
    cache = ct.ClaudeSessionCache(process_factory=process_factory)
    old = cache.get_or_create(tmp_path, [])
    new = cache.force_restart(tmp_path, [])
    old.backend.exited.emit(0)
    assert cache.get_or_create(tmp_path, []) is new
    assert old.backend.stops == 1
    cache.stop_all()


def test_claude_view_reuses_offline_renderer_and_replays_cached_session(app, tmp_path):
    cache = ct.ClaudeSessionCache(process_factory=process_factory)
    view = ct.ClaudeTerminalWidget(cache, surface_factory=lambda parent:
        DeepTerminalSurface(parent, web_view_factory=lambda p: QWidget(p)))
    view.show_for(tmp_path, [])
    first = view._current_process
    first.backend.output_received.emit(b"session output")
    renderer = view.output
    view.show_for(tmp_path, [])
    assert view.output is renderer
    assert view.output.toPlainText() == "session output"
    view.stop_session()
    assert first.is_running()
    view.show_for(tmp_path, [])
    assert view._current_process is first
    assert view.output.toPlainText() == "session output"
    assert "cdn.jsdelivr.net" not in build_deep_terminal_html()
    view.close()
    cache.stop_all()


def test_missing_claude_is_reported_without_leaving_cached_session(app, tmp_path, monkeypatch):
    monkeypatch.setattr(ct.shutil, "which", lambda _: None)
    cache = ct.ClaudeSessionCache(process_factory=process_factory)
    process = cache.get_or_create(tmp_path, [])
    output = []
    process.replay(output.append)
    assert b"not found" in b"".join(output)
    assert not process.is_running()
    assert not cache._sessions
