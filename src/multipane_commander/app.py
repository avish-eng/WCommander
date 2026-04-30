from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from multipane_commander.bootstrap import build_app_context
from multipane_commander.ui.main_window import MainWindow


def run() -> None:
    app = QApplication(sys.argv)
    context = build_app_context()
    window = MainWindow(context=context)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
