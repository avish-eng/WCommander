from __future__ import annotations

import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from multipane_commander.ui.deep_terminal import surface as surface_module
from multipane_commander.ui.deep_terminal.surface import (
    DeepTerminalBridge,
    DeepTerminalSurface,
    build_deep_terminal_html,
)


_APP: QApplication | None = None


def _qapp() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _APP = existing
    if _APP is None:
        _APP = QApplication([])
    return _APP


def _surface() -> DeepTerminalSurface:
    _qapp()
    return DeepTerminalSurface(web_view_factory=lambda parent: QWidget(parent))


def _decode_writes(surface: DeepTerminalSurface, collected: list[bytes]) -> None:
    surface._bridge.write_data.connect(
        lambda encoded: collected.append(base64.b64decode(encoded))
    )


def test_deep_terminal_html_has_modern_features_without_cdn() -> None:
    html = build_deep_terminal_html()

    assert "new Terminal(" in html
    assert "FitAddon.FitAddon" in html
    assert "SearchAddon.SearchAddon" in html
    assert "Unicode11Addon.Unicode11Addon" in html
    assert "WebLinksAddon.WebLinksAddon" in html
    assert "onDidChangeResults" in html
    assert "linkHandler" in html
    assert "allowProposedApi: true" in html
    assert "windowsPty" in html
    assert "window.mpcSearch" in html
    assert "window.mpcSetFontSize" in html
    assert "request_paste" in html
    assert "bridge.copy_text" in html
    assert "cdn.jsdelivr.net" not in html
    assert "qrc:///qtwebchannel/qwebchannel.js" in html


def test_app_enables_grayscale_text_antialiasing(monkeypatch) -> None:
    from multipane_commander.app import configure_webengine_flags

    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--existing-flag")
    configure_webengine_flags()

    assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] == "--existing-flag --disable-lcd-text"

    configure_webengine_flags()
    assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] == "--existing-flag --disable-lcd-text"


def test_app_forces_webengine_scale_to_the_screen_dpr(monkeypatch) -> None:
    from multipane_commander.app import configure_webengine_scale

    class FakeScreen:
        def devicePixelRatio(self) -> float:
            return 1.5

    class FakeApp:
        def screenAt(self, _point):
            return FakeScreen()

        def primaryScreen(self):
            return FakeScreen()

    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-lcd-text")
    configure_webengine_scale(FakeApp())

    flags = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
    assert "--force-device-scale-factor=1.5" in flags


def test_app_respects_an_explicit_webengine_scale(monkeypatch) -> None:
    from multipane_commander.app import configure_webengine_scale

    monkeypatch.setenv(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-lcd-text --force-device-scale-factor=2",
    )
    configure_webengine_scale(None)

    assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] == (
        "--disable-lcd-text --force-device-scale-factor=2"
    )


def test_deep_terminal_html_defaults_to_the_crisp_dom_renderer() -> None:
    html = build_deep_terminal_html()

    assert "WebglAddon" not in html


def test_deep_terminal_html_can_enable_the_gpu_renderer() -> None:
    html = build_deep_terminal_html(gpu_renderer=True)

    assert "WebglAddon.WebglAddon" in html
    assert "onContextLoss" in html


def test_deep_terminal_default_font_prefers_consolas() -> None:
    html = build_deep_terminal_html()

    assert '"Consolas, Cascadia Mono' in html
    assert "fontSize: 14" in html
    assert "function snapTerminalMetrics()" in html
    assert "function measureAdvance(" in html
    assert "logicalFontSize" in html


def test_deep_terminal_html_uses_configured_font() -> None:
    html = build_deep_terminal_html(font_family="JetBrains Mono", font_size=15)

    assert '"JetBrains Mono"' in html
    assert "fontSize: 15" in html
    assert "var defaultFontSize = 15" in html

    default = build_deep_terminal_html()
    assert "fontSize: 14" in default
    assert "var defaultFontSize = 14" in default


def test_deep_terminal_html_handles_clipboard_chords_inside_webengine() -> None:
    html = build_deep_terminal_html()

    assert "copyChord" in html
    assert "pasteChord" in html
    assert "term.hasSelection()" in html
    assert "bridge.copy_text(term.getSelection())" in html
    assert "bridge.request_paste()" in html
    assert "isMac && meta" in html


def test_deep_terminal_html_calls_bridge_slots_not_signals() -> None:
    html = build_deep_terminal_html()

    assert "bridge.request_search()" in html
    assert "bridge.notify_bell()" in html
    assert "bridge.notify_font_size(logicalFontSize)" in html
    assert "bridge.search_requested()" not in html
    assert "bridge.bell()" not in html
    assert "bridge.font_size_changed(" not in html


def test_deep_bridge_decodes_input_and_ignores_bad_base64() -> None:
    bridge = DeepTerminalBridge()
    received: list[bytes] = []
    bridge.input_received.connect(received.append)

    bridge.send_input(base64.b64encode("hello ☃".encode()).decode("ascii"))
    bridge.send_input("not-base64!!")

    assert received == ["hello ☃".encode()]


def test_deep_bridge_forwards_all_slots() -> None:
    bridge = DeepTerminalBridge()
    pastes: list[bool] = []
    resizes: list[tuple[int, int]] = []
    copies: list[str] = []
    links: list[str] = []
    titles: list[str] = []
    font_sizes: list[int] = []
    searches: list[bool] = []
    ready: list[bool] = []
    bridge.paste_requested.connect(lambda: pastes.append(True))
    bridge.terminal_resized.connect(lambda c, r: resizes.append((c, r)))
    bridge.copy_requested.connect(copies.append)
    bridge.open_link_requested.connect(links.append)
    bridge.title_changed.connect(titles.append)
    bridge.font_size_changed.connect(font_sizes.append)
    bridge.search_requested.connect(lambda: searches.append(True))
    bridge.ready.connect(lambda: ready.append(True))

    bridge.request_paste()
    bridge.resize_terminal(80, 24)
    bridge.resize_terminal(-1, 0)
    bridge.copy_text("copied")
    bridge.open_link("https://example.com")
    bridge.set_title("shell")
    bridge.request_search()
    bridge.notify_font_size(15)
    bridge.terminal_ready()

    assert pastes == [True]
    assert resizes == [(80, 24)]
    assert copies == ["copied"]
    assert links == ["https://example.com"]
    assert titles == ["shell"]
    assert font_sizes == [15]
    assert searches == [True]
    assert ready == [True]


def test_surface_coalesces_output_into_one_write() -> None:
    surface = _surface()
    collected: list[bytes] = []
    _decode_writes(surface, collected)
    surface._page_ready = True

    surface.append_output(b"first")
    surface.append_output(b"")
    surface.append_output(b"second")
    assert collected == []

    surface._flush_output()

    assert collected == [b"firstsecond"]


def test_surface_replays_buffered_output_when_page_becomes_ready() -> None:
    surface = _surface()
    collected: list[bytes] = []
    _decode_writes(surface, collected)

    surface.append_output(b"early ")
    surface._flush_output()
    assert collected == []

    surface._handle_ready()
    surface.append_output(b"late")
    surface._flush_output()

    assert collected == [b"early ", b"late"]
    assert surface._page_ready is True


def test_surface_queues_input_until_ready() -> None:
    surface = _surface()
    sent: list[bytes] = []
    surface.set_sender(sent.append)
    surface.set_input_ready(False)

    surface.inject_command("echo hi", run=True)
    assert sent == []

    surface.set_input_ready(True)

    assert sent == [b"echo hi", b"\r"]


def test_surface_inject_command_tracks_draft_and_submits() -> None:
    surface = _surface()
    submitted: list[str] = []
    sent: list[bytes] = []
    surface.set_sender(sent.append)
    surface.command_submitted.connect(submitted.append)

    surface.inject_command("git status", run=False)
    assert surface.current_draft() == "git status"
    assert sent == [b"git status"]

    surface.inject_command(" --short", run=True)

    assert sent == [b"git status", b" --short", b"\r"]
    assert submitted == ["git status --short"]
    assert surface.current_draft() == ""


def test_surface_handle_input_emits_submitted_and_sends_bytes() -> None:
    surface = _surface()
    sent: list[bytes] = []
    submitted: list[str] = []
    surface.set_sender(sent.append)
    surface.command_submitted.connect(submitted.append)

    surface._bridge.input_received.emit(b"ls -la\r")

    assert sent == [b"ls -la\r"]
    assert submitted == ["ls -la"]


def test_surface_paste_dedupes_only_within_short_window(monkeypatch) -> None:
    surface = _surface()
    sent: list[bytes] = []
    surface.set_sender(sent.append)
    QApplication.clipboard().setText("pasted")
    clock = iter([1.0, 1.01, 2.0])
    monkeypatch.setattr("multipane_commander.ui.deep_terminal.surface.time.monotonic", lambda: next(clock))

    surface.paste_from_clipboard()
    surface.paste_from_clipboard()
    surface.paste_from_clipboard()

    assert sent == [b"pasted", b"pasted"]


def test_surface_copy_writes_page_selection_to_clipboard() -> None:
    surface = _surface()
    QApplication.clipboard().clear()
    surface._page_ready = True
    surface._handle_copy("selected text")
    assert QApplication.clipboard().text() == "selected text"


def test_surface_to_plain_text_is_bounded() -> None:
    surface = _surface()
    surface._plain_chunks = ["a" * 150_000, "b" * 150_000]
    surface._plain_length = 300_000
    surface._append_plain(b"c" * 150_000)

    text = surface.toPlainText()

    assert len(text) <= surface_module._MAX_PLAIN_OUTPUT
    assert text.endswith("c" * 150_000)


def test_surface_clear_resets_buffers() -> None:
    surface = _surface()
    surface.append_output(b"stale")
    surface._handle_input(b"draft")
    surface.clear()

    assert surface.toPlainText() == ""
    assert surface.current_draft() == ""
    assert surface._pending_output == bytearray()


def test_surface_font_size_is_clamped_and_reported() -> None:
    surface = _surface()
    reported: list[int] = []
    surface.font_size_changed.connect(reported.append)

    surface._handle_font_size(2)
    assert surface.font_size() == 6

    surface._handle_font_size(99)
    assert surface.font_size() == 40
    assert reported == [6, 40]


def test_surface_search_is_a_noop_without_a_page() -> None:
    surface = _surface()
    surface.search("needle")
    surface.clear_search()
    surface.selectAll()

    assert surface.search_result is not None


def test_create_deep_surface_raises_without_webengine(monkeypatch) -> None:
    monkeypatch.setattr(surface_module, "WEB_TERMINAL_AVAILABLE", False)
    import pytest

    with pytest.raises(RuntimeError):
        surface_module.create_deep_surface()


def test_surface_viewport_is_the_web_view() -> None:
    surface = _surface()

    assert surface.viewport() is surface._view


class _FakePage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def runJavaScript(self, script, callback=None) -> None:
        self.calls.append((script, callback))
        if callback is None:
            return
        if "mpcGetSelection" in script:
            callback("selected text")
        elif "mpcGetFontSize" in script:
            callback(16)
        else:
            callback(None)


class _FakeWebView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.fake_page = _FakePage()

    def page(self) -> _FakePage:
        return self.fake_page


def _scripted_surface() -> DeepTerminalSurface:
    _qapp()
    surface = DeepTerminalSurface(web_view_factory=lambda parent: _FakeWebView(parent))
    surface._page_ready = True
    return surface


def test_surface_routes_javascript_features_to_the_page() -> None:
    surface = _scripted_surface()
    page = surface._view.fake_page
    results: list[tuple[int, int]] = []
    surface.search_result.connect(lambda c, i: results.append((c, i)))

    surface.search("needle")
    surface.set_font_size(16)
    surface.selectAll()
    surface.clear_search()
    surface.focus_input()

    scripts = [script for script, _callback in page.calls]
    assert any("mpcSearch(" in script for script in scripts)
    assert any("mpcSetFontSize(16)" in script for script in scripts)
    assert any("mpcSelectAll" in script for script in scripts)
    assert any("mpcClearSearch" in script for script in scripts)
    assert any("mpcFocus" in script for script in scripts)

    surface._bridge.search_results(2, 0)
    assert results == [(2, 0)]


def test_surface_copy_uses_page_selection_callback() -> None:
    surface = _scripted_surface()
    QApplication.clipboard().clear()

    surface.copy()

    assert QApplication.clipboard().text() == "selected text"


def test_surface_clear_routes_to_page_when_ready() -> None:
    surface = _scripted_surface()

    surface.clear()

    scripts = [script for script, _callback in surface._view.fake_page.calls]
    assert any("mpcClear" in script for script in scripts)
