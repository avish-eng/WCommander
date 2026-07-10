from __future__ import annotations

import base64

from multipane_commander.ui.xterm_surface import (
    XtermBridge,
    build_xterm_html,
    update_draft_from_input,
)


def test_xterm_page_uses_vendored_assets() -> None:
    html = build_xterm_html()

    assert "new Terminal(" in html
    assert "FitAddon.FitAddon" in html
    assert "bridge.request_paste()" in html
    assert "term.paste(text)" in html
    assert "cdn.jsdelivr.net" not in html


def test_xterm_bridge_decodes_input() -> None:
    bridge = XtermBridge()
    received: list[bytes] = []
    bridge.input_received.connect(received.append)

    bridge.send_input(base64.b64encode("hello ☃".encode()).decode("ascii"))

    assert received == ["hello ☃".encode()]


def test_xterm_bridge_requests_native_clipboard_paste() -> None:
    bridge = XtermBridge()
    requested: list[bool] = []
    bridge.paste_requested.connect(lambda: requested.append(True))

    bridge.request_paste()

    assert requested == [True]


def test_xterm_command_tracker_handles_edits_and_ignores_navigation() -> None:
    draft, submitted = update_draft_from_input("", b"echo worlx\x7fd\x1b[A\r")

    assert draft == ""
    assert submitted == ["echo world"]
