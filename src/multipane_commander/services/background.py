"""Cancellable Qt pool tasks; results are delivered on the receiver's thread."""

from __future__ import annotations

from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Signals(QObject):
    finished = Signal(str, int, object, object)
    batch = Signal(str, int, object)


class _Task(QRunnable):
    def __init__(self, key, generation, function, cancelled, signals):
        super().__init__()
        self.key, self.generation = key, generation
        self.function, self.cancelled, self.signals = function, cancelled, signals

    def run(self):
        result = error = None
        try:
            result = self.function(
                self.cancelled,
                lambda data: self.signals.batch.emit(self.key, self.generation, data),
            )
        except Exception as exc:
            error = exc
        self.signals.finished.emit(self.key, self.generation, result, error)


class BackgroundTasks(QObject):
    finished = Signal(str, object, object)
    batch = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._signals = _Signals()
        self._signals.finished.connect(self._finished)
        self._signals.batch.connect(self._batch)
        self._active: dict[str, tuple[int, Event]] = {}
        self._generation = 0
        # Only capture plain state; cancellation also works during QObject destruction.
        active = self._active
        self.destroyed.connect(lambda: [token.set() for _, token in active.values()])

    def submit(self, key, function):
        self.cancel(key)
        self._generation += 1
        token = Event()
        self._active[key] = (self._generation, token)
        QThreadPool.globalInstance().start(
            _Task(key, self._generation, function, token, self._signals)
        )

    def cancel(self, key):
        current = self._active.pop(key, None)
        if current:
            current[1].set()

    def cancel_all(self):
        for key in list(self._active):
            self.cancel(key)

    def is_running(self, key):
        return key in self._active

    @Slot(str, int, object, object)
    def _finished(self, key, generation, result, error):
        if key not in self._active or self._active[key][0] != generation:
            return
        self._active.pop(key)
        self.finished.emit(key, result, error)

    @Slot(str, int, object)
    def _batch(self, key, generation, data):
        if key in self._active and self._active[key][0] == generation:
            self.batch.emit(key, data)
