from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from services.serial import list_com_ports
from .use_connection import ConnectionController

STEP_TIMEOUT_MS = 500  # generous - includes opening the port plus a real round trip

# A module whose wires were just physically reconnected (swapping which one
# is wired to a shared port) may not be electrically ready the instant the
# OS reports the port open - line capacitance settling, the module's own
# UART re-syncing, etc. Sending the very first query immediately after
# open() risks it landing before the module can actually hear it, which
# looks identical to "nothing is there" even though it is. This delay
# only applies once per port, before the first query at each baud.
SETTLE_DELAY_MS = 250

# Tried in order on a port that doesn't answer at the configured baud, before
# giving up on it entirely. A slower baud gives each bit a longer window,
# which can be the difference between unreadable noise and a legible frame
# on a line under electrical contention (two drivers on one shared wire) -
# doesn't cost anything to try, no hardware/wiring change involved.
FALLBACK_BAUDS = [57600, 38400, 19200, 9600]


class DiscoveryController(QObject):
    """Probes every available serial port one at a time - not addresses
    on a shared bus. The modules are wired point-to-point over RS422
    (confirmed on real hardware: two modules sharing one USB-RS422
    adapter produce no usable response at all, consistent with RS422
    being a point-to-point interface, not a true multi-drop bus like
    RS485), so each port can only ever have one module on it. One
    dedicated ConnectionController is opened per module - see
    ChannelManager, which keeps them alive for as long as that channel
    exists instead of sharing a single connection across channels.

    For each port: open it, broadcast an Address Query ("who's there?"
    - safe now, since there's only ever one device per port to answer,
    unlike the old shared-bus scan where a broadcast would make every
    module answer at once and collide), and if something answers, seed
    its Mode/Frequency/Bandwidth/Power baseline with a Status Query
    before handing the connected, addressed channel off to the caller.
    A port with nothing useful on it (timeout either step) is released
    and skipped.
    """

    channel_found = Signal(str, int, object, object)  # port, address, ConnectionController, initial status frame
    progress = Signal(int, int)
    finished = Signal()

    def __init__(self, baud: int, parity: str, data_bits: int, max_ports: int, logger=None):
        super().__init__()
        self.baud = baud
        self.parity = parity
        self.data_bits = data_bits
        self.max_ports = max_ports
        self.logger = logger
        self._baud_candidates = [baud] + [b for b in FALLBACK_BAUDS if b != baud]
        self._ports: list[str] = []
        self._index = 0
        self._baud_index = 0
        self._conn: ConnectionController | None = None
        self._addr: int | None = None
        self._scanning = False

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    def start(self, exclude_ports=frozenset()):
        if self._scanning:
            return
        available = [p for p in list_com_ports() if p not in exclude_ports]
        self._ports = available[: self.max_ports]
        self._index = 0
        self._baud_index = 0
        self._scanning = True
        self._probe_next()

    def _probe_next(self):
        if self._index >= len(self._ports):
            self._finish()
            return
        self.progress.emit(self._index + 1, len(self._ports))
        port = self._ports[self._index]
        baud = self._baud_candidates[self._baud_index]
        if self.logger:
            self.logger.info(f"Discovery: probing port {port} at {baud} baud")

        conn = ConnectionController()
        if not conn.connect(port, baud, self.parity, self.data_bits):
            self._advance_port()
            return

        self._conn = conn
        self._addr = None
        conn.frame_received.connect(self._on_frame)
        conn.raw_rx.connect(self._on_raw_rx)
        QTimer.singleShot(SETTLE_DELAY_MS, self._send_address_query)

    def _send_address_query(self):
        # Guard against the scan having moved on (timeout, stop(), or a
        # response already arrived some other way) during the settle delay.
        if self._conn is None:
            return
        self._conn.send(commands.query_address())
        self._timer.start(STEP_TIMEOUT_MS)

    def _on_raw_rx(self, data: bytes):
        # Logged even when nothing parses into a valid frame - the only
        # way to tell "truly nothing came back" apart from "something
        # came back but wasn't a legal frame" (wrong baud, corrupted by
        # collision, a device that talks a different protocol, etc.),
        # which otherwise look identical from the outside as one
        # generic timeout.
        if self.logger:
            port = self._ports[self._index] if self._index < len(self._ports) else "?"
            self.logger.info(f"Discovery: raw bytes on {port}: {data.hex(' ').upper()}")

    def _on_frame(self, frame: ParsedFrame):
        if not self._scanning or self._conn is None:
            return
        if self._addr is None:
            if frame.type == c.TYPE_ADDR_QUERY and len(frame.buf) == 1:
                self._timer.stop()
                self._addr = frame.buf[0]
                self._conn.send(commands.query_status(self._addr))
                self._timer.start(STEP_TIMEOUT_MS)
        elif frame.type == c.TYPE_STATUS_QUERY and frame.addr == self._addr and len(frame.buf) >= 6:
            self._timer.stop()
            conn, addr, port = self._conn, self._addr, self._ports[self._index]
            conn.frame_received.disconnect(self._on_frame)
            conn.raw_rx.disconnect(self._on_raw_rx)
            self._conn = None
            self._addr = None
            self.channel_found.emit(port, addr, conn, frame)
            self._advance_port()

    def _on_timeout(self):
        # Nothing usable answered on this port within the window at this
        # baud rate - release the connection and either try the next
        # fallback baud on the SAME port, or give up on the port entirely
        # once every candidate baud has been tried.
        if self._conn is not None:
            self._conn.frame_received.disconnect(self._on_frame)
            self._conn.raw_rx.disconnect(self._on_raw_rx)
            self._conn.disconnect()
            self._conn = None
        self._addr = None

        if self._baud_index + 1 < len(self._baud_candidates):
            self._baud_index += 1
            self._probe_next()
        else:
            self._advance_port()

    def _advance_port(self):
        self._index += 1
        self._baud_index = 0
        self._probe_next()

    def _finish(self):
        self._scanning = False
        self.finished.emit()

    def stop(self):
        """Cancel an in-progress scan, releasing whatever port is
        currently being probed. Must be called on app shutdown - a scan
        left running mid-probe leaves a live serial thread that gets
        torn down uncleanly (a real crash, not just a warning) if the
        process exits while it's still going."""
        self._timer.stop()
        if self._conn is not None:
            self._conn.frame_received.disconnect(self._on_frame)
            self._conn.raw_rx.disconnect(self._on_raw_rx)
            self._conn.disconnect()
            self._conn = None
        self._addr = None
        self._scanning = False
