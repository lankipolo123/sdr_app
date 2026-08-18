import os

from PySide6.QtCore import QObject, QTimer, Signal

from services.middleware import Token, dispatch_token, dll_log_text
from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState
from utils.channel_store import load_channel_states, save_channel_states
from .use_channel import ChannelController
from .use_connection import ConnectionController
from .use_port_scheduler import PortScheduler

MAX_CHANNELS = 16  # ceiling on how many addresses the UI shows cards for

QUERY_TIMEOUT_MS = 300
QUERY_MAX_ATTEMPTS = 4  # re-send the targeted query a few times before giving up


class ChannelManager(QObject):
    """Owns one ChannelController per address, all 16 live from the
    moment the app starts. There's no discovery/scan step and no
    online/offline distinction anymore - every ChannelController already
    brute-force finds and opens its own port fresh for every command it
    sends (see hooks/use_channel.py), with retries and an optimistic
    apply-on-timeout if nothing answers. That's strictly better than
    requiring a prior Scan or +Addr response before a channel becomes
    controllable: on a shared/collision-prone line, waiting for a
    confirmed discovery response first only means waiting for something
    that might never come, when the blind command would have gotten
    through anyway."""

    command_timeout = Signal(str)
    raw_tx = Signal(int, bytes)          # address, bytes sent
    raw_rx = Signal(int, bytes)          # address, bytes received

    def __init__(self, config_service, logger=None):
        super().__init__()
        self.config = config_service
        self.logger = logger
        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)

        # Lives next to config.json, in whatever directory THIS
        # ConfigService instance actually points at - not a fixed global
        # path, or every ConfigService instance (e.g. two isolated test
        # runs, each with their own tmp config dir) would read/write the
        # exact same real channels.ini and cross-contaminate each other's
        # channel state.
        self._channels_path = os.path.join(os.path.dirname(self.config.path), "channels.ini")

        # Shared by every channel AND Query - there's only one physical
        # port on the confirmed real wiring, so only one command anywhere
        # is ever allowed to actively use it at a time (see
        # use_port_scheduler.py). Without this, two channels used close
        # together could each try to open the same port at once and
        # collide, repeatedly failing and freezing the GUI while they
        # fought over it.
        self.port_scheduler = PortScheduler()

        # Every channel's own mode/power/output is persisted to a single
        # flat .ini file (see utils/channel_store.py), not this JSON
        # config - read once up front rather than re-reading the file
        # for every one of the 16 channels being constructed.
        saved_states = load_channel_states(self._channels_path)

        self.states: dict[int, ChannelState] = {}
        self.controllers: dict[int, ChannelController] = {}
        for address in range(MAX_CHANNELS):
            state = self._make_state(address, saved_states.get(address))
            controller = ChannelController(
                state, baud, parity, data_bits, self.logger, port_scheduler=self.port_scheduler,
            )
            controller.command_timeout.connect(self.command_timeout.emit)
            # wire_address (not the raw 0-based address) so this matches
            # the CH number everywhere else a controller identifies
            # itself - see ChannelController.wire_address.
            controller.raw_tx.connect(lambda data, ctrl=controller: self.raw_tx.emit(ctrl.wire_address, data))
            controller.raw_rx.connect(lambda data, ctrl=controller: self.raw_rx.emit(ctrl.wire_address, data))
            self.states[address] = state
            self.controllers[address] = controller

    def _make_state(self, address: int, saved: dict | None) -> ChannelState:
        state = ChannelState(address)
        if saved:
            # UI-only restore - shows the card looking like it did last
            # session (mode dropdown, slider position, toggle state), but
            # nothing here actually sends a command. Matches the app's
            # existing "nothing happens automatically on launch" design
            # (no auto-scan, no auto-query) - a real send only ever
            # follows an explicit tap/interaction with that specific card.
            if "mode" in saved:
                state.data.mode = saved["mode"]
            if "last_level" in saved:
                state.data.last_level = saved["last_level"]
            if "output_on" in saved:
                state.data.output_on = saved["output_on"]
        return state

    def get_controller(self, address: int) -> ChannelController:
        return self.controllers[address]

    def get_state(self, address: int) -> ChannelState:
        return self.states[address]

    def send_token(self, token: Token) -> None:
        """Entry point for an external caller (Transit.dll, eventually)
        that only knows "channel N, do X" - never a ChannelController
        object, and never a raw hex command. Looks up the right
        controller for token.channel and hands off to
        services.middleware.dispatch_token(), which validates the
        token before it ever reaches real hardware - see
        services/middleware.py for what that validation actually
        blocks."""
        controller = self.get_controller(token.channel - 1)  # Token uses CH01-16, get_controller uses the internal 0-based address
        dispatch_token(controller, token)

    def brute_force_query(self, address: int, on: bool):
        """Standalone diagnostic, separate from the cards: type in one
        address, brute-force finds an available port the same way every
        real command does (see ConnectionController.list_ports() /
        ChannelController._find_and_open_connection), sends Output ON/OFF
        to it, and actually waits for and verifies the response -
        retrying up to QUERY_MAX_ATTEMPTS times - instead of firing
        blind. Doesn't touch states/controllers or build a card; this
        isn't a real channel connection, just a one-off check.

        The actual attempt/retry/port-sweep sequence lives in
        _QueryAttempt below, one instance per call, so this method just
        validates ports exist and hands off."""
        ports = ConnectionController.list_ports()
        if not ports:
            self.command_timeout.emit("Query: no ports available.")
            return

        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)
        _QueryAttempt(self, address, on, ports, baud, parity, data_bits).start()

    def save_all(self):
        save_channel_states(self.states, self._channels_path)

    def shutdown(self):
        for controller in self.controllers.values():
            controller.cancel_pending()


class _QueryAttempt(QObject):
    """One brute-force Query run: sweep every available port, and on
    each one retry up to QUERY_MAX_ATTEMPTS times before moving to the
    next port, exactly like a ChannelController's own retry loop.

    A plain object (not the queue-based reuse a ChannelController gets)
    since Query is a one-off diagnostic, not a persistent per-channel
    connection - each call to ChannelManager.brute_force_query() builds
    a fresh instance and throws it away once it resolves. Goes through
    the same shared port_scheduler every channel does, using itself as
    the scheduler's identity token (see PortScheduler) - without that,
    Query could collide with a card's in-flight command the exact same
    way two channels used close together used to collide with each
    other."""

    def __init__(self, manager: "ChannelManager", address: int, on: bool,
                 ports: list[str], baud: int, parity: str, data_bits: int):
        super().__init__(parent=manager)
        self.manager = manager
        self.address = address
        self.ports = ports
        self.baud = baud
        self.parity = parity
        self.data_bits = data_bits
        self.label = "ON" if on else "OFF"
        self.frame = commands.output_on(address) if on else commands.output_off(address)

        self.port_index = -1
        self.conn: ConnectionController | None = None
        self.attempts = 0
        self.raw_seen = False

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._on_timeout)

    def start(self):
        self._advance_port()

    def _close_conn(self):
        if self.conn is None:
            return
        self.conn.frame_received.disconnect(self._on_frame)
        self.conn.raw_tx.disconnect(self._on_raw_tx)
        self.conn.raw_rx.disconnect(self._on_raw_rx)
        self.conn.disconnect()
        self.conn = None

    def _on_raw_tx(self, data: bytes):
        self.manager.raw_tx.emit(self.address, data)

    def _on_raw_rx(self, data: bytes):
        self.raw_seen = True
        port = self.ports[self.port_index]
        if self.manager.logger:
            # No raw hex in the log, same rule as the GUI - see
            # services/middleware.py's dll_log_text().
            self.manager.logger.info(f"Query: raw bytes on {port}: {dll_log_text(data)}")
        self.manager.raw_rx.emit(self.address, data)

    def _on_frame(self, response: ParsedFrame):
        if response.type != c.TYPE_OUTPUT_SWITCH or response.addr != self.address:
            return
        self.timer.stop()
        self._close_conn()
        self.manager.port_scheduler.release(self)
        success = len(response.buf) == 1 and response.buf[0] == c.RESP_SUCCESS
        port = self.ports[self.port_index]
        self.manager.command_timeout.emit(
            f"Query: {self.label} to address {self.address} on {port} - "
            f"{'confirmed' if success else 'device rejected it'} "
            f"(attempt {self.attempts}/{QUERY_MAX_ATTEMPTS})."
        )

    def _request_attempt(self):
        # Asks for the port for exactly ONE attempt (open, send, wait)
        # rather than for this whole address's entire sweep-and-retry
        # cycle - otherwise an unanswering address would hold the shared
        # port for up to QUERY_MAX_ATTEMPTS * len(ports) attempts in a
        # row, freezing every channel card queued behind it for that
        # whole stretch.
        self.manager.port_scheduler.acquire(self, self._on_port_granted)

    def _on_port_granted(self):
        port = self.ports[self.port_index]
        conn = ConnectionController()
        if not conn.connect(port, self.baud, self.parity, self.data_bits):
            if self.manager.logger:
                self.manager.logger.info(f"Query: failed to open {port}, trying next port.")
            self.manager.port_scheduler.release(self)
            self._advance_port()
            return
        self.conn = conn
        conn.raw_tx.connect(self._on_raw_tx)
        conn.raw_rx.connect(self._on_raw_rx)
        conn.frame_received.connect(self._on_frame)
        self._send_attempt()

    def _send_attempt(self):
        self.attempts += 1
        self.raw_seen = False
        port = self.ports[self.port_index]
        if self.manager.logger:
            self.manager.logger.info(
                f"Query: {self.label} to address {self.address} on {port} "
                f"(attempt {self.attempts}/{QUERY_MAX_ATTEMPTS})"
            )
        self.conn.send(self.frame)
        self.timer.start(QUERY_TIMEOUT_MS)

    def _advance_port(self):
        self.port_index += 1
        self.attempts = 0
        if self.port_index >= len(self.ports):
            msg = f"Query: no response from address {self.address} after trying {len(self.ports)} port(s)."
            if self.manager.logger:
                self.manager.logger.warning(msg)
            self.manager.command_timeout.emit(msg)
            return
        self._request_attempt()

    def _on_timeout(self):
        port = self.ports[self.port_index]
        if self.manager.logger:
            status = "bytes came back but never formed a valid response" if self.raw_seen else \
                "zero bytes received, nothing came back at all"
            self.manager.logger.info(f"Query: attempt {self.attempts} timed out on {port} - {status}.")
        self._close_conn()
        self.manager.port_scheduler.release(self)
        if self.attempts < QUERY_MAX_ATTEMPTS:
            self._request_attempt()
            return
        self._advance_port()
