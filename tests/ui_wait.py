"""Wait for real asynchronous work while continuing to deliver Qt events."""

import time

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for asynchronous UI work")
        time.sleep(0.005)


def wait_for_pane(pane):
    wait_until(lambda: not pane._tasks.is_running("directory") and not pane._rendering)
