from collections import deque

from PySide6.QtCore import QObject


class PortScheduler(QObject):

    def __init__(self):
        super().__init__()
        self._queue: deque = deque()
        self._holder = None

    def acquire(self, requester, on_granted):
        if self._holder is None:
            self._holder = requester
            on_granted()
            return
        self._queue.append((requester, on_granted))

    def release(self, requester):
        if self._holder is not requester:
            return
        self._holder = None
        self._advance()

    def cancel(self, requester):
        self._queue = deque((r, cb) for r, cb in self._queue if r is not requester)
        if self._holder is requester:
            self._holder = None
            self._advance()

    def _advance(self):
        if not self._queue:
            return
        requester, on_granted = self._queue.popleft()
        self._holder = requester
        on_granted()
