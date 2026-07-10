from __future__ import annotations

import os
import sys
from pathlib import Path

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


def run() -> None:
    setup_logging()
    configure_native_runtime()
    app = QApplication(sys.argv)
    context = build_app_context()
    if context.config.env_path.entries:
        set_process_path_entries(context.config.env_path.entries)
    window = MainWindow(context=context)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
