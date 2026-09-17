from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from multipane_commander.bootstrap import build_app_context
from multipane_commander.log import setup_logging
from multipane_commander.services.env_path import set_process_path_entries
from multipane_commander.ui.main_window import MainWindow


def _windows_archiveint_path() -> Path:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return Path(system_root) / "System32" / "archiveint.dll"


def configure_native_runtime() -> None:
    if os.name != "nt" or os.environ.get("LIBARCHIVE"):
        return
    archiveint = _windows_archiveint_path()
    if archiveint.is_file():
        os.environ["LIBARCHIVE"] = str(archiveint)


def configure_webengine_flags() -> None:
    """Use grayscale text antialiasing inside QtWebEngine.

    Chromium's LCD subpixel antialiasing produces uneven stems and colour
    fringing at fractional display scaling (e.g. Windows 120%/150%), which is
    very visible in the terminal's thin monospace glyphs. Must run before the
    first QtWebEngine view is created.
    """
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--disable-lcd-text" not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{flags} --disable-lcd-text".strip()


def configure_webengine_scale(app: QApplication) -> None:
    """Match Chromium's device scale factor to the screen Qt composites on.

    QtWebEngine can report a device scale factor that differs from the widget's
    per-monitor DPR (e.g. a system-wide 120% while Qt uses 100% or 150%). The
    web view is then resampled when composited, which softens text and breaks
    single-pixel glyph features. Forcing the scale keeps 1 CSS pixel equal to
    1 device pixel, so the terminal renders pixel-exact.

    Must run after QApplication exists (to read the screen) but before the
    first QtWebEngine view is created, and never overrides an explicit
    user-supplied factor.
    """
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--force-device-scale-factor" in flags:
        return
    screen = app.screenAt(QCursor.pos()) or app.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    if dpr <= 0:
        dpr = 1.0
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        f"{flags} --force-device-scale-factor={dpr:g}".strip()
    )


def run() -> None:
    setup_logging()
    configure_native_runtime()
    configure_webengine_flags()
    app = QApplication(sys.argv)
    configure_webengine_scale(app)
    context = build_app_context()
    if context.config.env_path.entries:
        set_process_path_entries(context.config.env_path.entries)
    window = MainWindow(context=context)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
