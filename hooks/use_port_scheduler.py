from collections import deque

from PySide6.QtCore import QObject


class PortScheduler(QObject):
    """Shared by every ChannelController AND the standalone Query
    diagnostic (see ChannelManager) - there's only one physical port on
    the confirmed real wiring, so only one command is ever allowed to
    actively use it at a time.

    Before this existed, two different channels (or a channel and
    Query) could each try to open their own connection to the same
    port at once. On Windows a COM port is exclusive-access, so
    whichever one lost the race just kept failing to open it and
    retrying blind against a port it could never get - freezing the
    GUI thread on every failed retry (see
    ConnectionController.connect's retry-with-sleep) while the other
    was still legitimately using it.

    Now a request made while the port is busy just waits its turn in a
    plain FIFO queue instead - no colliding attempts, no wasted
    retries, and nothing to block on while it waits."""

    def __init__(self):
        super().__init__()
        self._queue: deque = deque()
        self._holder = None

    def acquire(self, requester, on_granted):
        """Ask for exclusive use of the port. on_granted() runs
        immediately if nobody's using it right now, or once it's this
        requester's turn otherwise. Whoever calls this MUST call
        release() (or cancel(), if tearing down) once done, even on
        failure - otherwise nothing else waiting ever gets a turn."""
        if self._holder is None:
            self._holder = requester
            on_granted()
            return
        self._queue.append((requester, on_granted))

    def release(self, requester):
        """Call once the requester's command is fully resolved (ack,
        rejection, or retries exhausted) - hands the port to whoever's
        next in line, if anyone. A no-op if requester isn't actually
        the current holder (e.g. it never acquired in the first
        place, or already released)."""
        if self._holder is not requester:
            return
        self._holder = None
        self._advance()

    def cancel(self, requester):
        """Call if a requester is torn down (e.g. a manual disconnect,
        or app shutdown) while it might still be holding the port OR
        still waiting in line for it - either way, it must not leave
        something else waiting forever for a turn that will never
        come."""
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
