import threading


class Signal:
    """Framework-free stand-in for PySide6.QtCore.Signal - a plain list of
    subscriber callables. Used by hooks/ and state/ so the app's actual
    control-flow logic (queuing, retries, state notification) didn't have
    to change when the UI moved off Qt, just what it's built on."""

    def __init__(self):
        self._subscribers = []

    def connect(self, callback):
        self._subscribers.append(callback)

    def disconnect(self, callback=None):
        if callback is None:
            self._subscribers.clear()
            return
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def emit(self, *args):
        for callback in list(self._subscribers):
            callback(*args)


class SingleShotTimer:
    """Stand-in for a QTimer(singleShot=True). Backed by threading.Timer,
    which fires on its own thread (Qt's timer callbacks all ran on the one
    Qt event-loop thread) - the generation counter makes stop() reliable
    even if a fire was already in flight when it's called, closing the
    race threading.Timer.cancel() alone doesn't."""

    def __init__(self):
        self.timeout = Signal()
        self._timer = None
        self._generation = 0

    def start(self, ms: int):
        self.stop()
        self._generation += 1
        generation = self._generation
        self._timer = threading.Timer(ms / 1000, self._fire, args=(generation,))
        self._timer.daemon = True
        self._timer.start()

    def stop(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._generation += 1

    def _fire(self, generation: int):
        if generation != self._generation:
            return
        self.timeout.emit()
