from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame

STEP_TIMEOUT_MS = 300  # short - a real module answers fast; no answer means nothing's there


class DiscoveryController(QObject):
    """Probes real protocol addresses 0..max_channels-1 one at a time with
    an addressed Status Query, and builds the channel list from whichever
    addresses actually answer.

    This is genuinely new logic - the old app's query_address() sends a
    *broadcast* ("what's your address?") intended for exactly one fresh
    module on the bus at a time. With several modules already addressed
    and connected, a broadcast would make all of them answer at once and
    collide. So discovery here goes one address at a time instead, and
    reuses each address's own Status Query response both to confirm the
    channel exists AND to seed its initial Mode/Frequency/Bandwidth/Power -
    no separate follow-up query needed.
    """

    channel_found = Signal(int, object)   # address, ParsedFrame (initial status)
    progress = Signal(int, int)           # current, total
    finished = Signal()

    def __init__(self, connection_controller, max_channels: int = 16, logger=None):
        super().__init__()
        self.conn = connection_controller
        self.max_channels = max_channels
        self.logger = logger
        self._addr = 0
        self._scanning = False
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    def start(self):
        if self._scanning:
            return
        self._scanning = True
        self._addr = 0
        self.conn.frame_received.connect(self._on_frame)
        self._probe_next()

    def _probe_next(self):
        if self._addr >= self.max_channels:
            self._finish()
            return
        self.progress.emit(self._addr + 1, self.max_channels)
        if self.logger:
            self.logger.info(f"Discovery: probing address {self._addr}")
        self.conn.send(commands.query_status(self._addr))
        self._timer.start(STEP_TIMEOUT_MS)

    def _on_frame(self, frame: ParsedFrame):
        if not self._scanning:
            return
        if frame.type == c.TYPE_STATUS_QUERY and frame.addr == self._addr and len(frame.buf) >= 6:
            self._timer.stop()
            self.channel_found.emit(self._addr, frame)
            self._addr += 1
            self._probe_next()

    def _on_timeout(self):
        self._addr += 1
        self._probe_next()

    def _finish(self):
        self._scanning = False
        self.conn.frame_received.disconnect(self._on_frame)
        self.finished.emit()
