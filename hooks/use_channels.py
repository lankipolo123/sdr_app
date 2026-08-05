from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState
from state.level_map import LEVEL_TO_DB
from .use_channel import ChannelController
from .use_connection import ConnectionController
from .use_discovery import DiscoveryController

MAX_CHANNELS = 16  # ceiling on how many ports we'll ever probe at once

MANUAL_TIMEOUT_MS = 500
MANUAL_MAX_ATTEMPTS = 6  # re-send the targeted query a few times before giving up


class ChannelManager(QObject):
    """Normally owns one dedicated ConnectionController per discovered
    channel - each module has its own serial port (RS422 is point-to-
    point, not a shared bus). The one exception is +Addr (
    add_manual_channel): asking a second address on a port that already
    has a live channel reuses that connection rather than requiring a
    disconnect first, so a single physically-shared adapter can still be
    asked about more than one address without a full swap cycle each
    time. Frames are routed to the right channel by address
    (_dispatch_frame) rather than wired directly to one controller, so
    that sharing doesn't cross-talk between addresses."""

    channel_added = Signal(int)          # address - seen for the first time this session
    channel_online = Signal(int)         # address - a known channel is live/controllable again
    channel_offline = Signal(int)        # address - a known channel's connection was released
    discovery_progress = Signal(int, int)
    discovery_finished = Signal()
    command_timeout = Signal(str)
    raw_tx = Signal(int, bytes)          # address, bytes sent
    raw_rx = Signal(int, bytes)          # address, bytes received

    def __init__(self, config_service, logger=None):
        super().__init__()
        self.config = config_service
        self.logger = logger
        self.states: dict[int, ChannelState] = {}
        self.controllers: dict[int, ChannelController] = {}
        self.connections: dict[int, ConnectionController] = {}
        self._claimed_ports: set[str] = set()
        self._address_port: dict[int, str] = {}
        self._dispatch_wired: set[int] = set()  # id(conn) already routed through _dispatch_frame

        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)
        self._discovery = DiscoveryController(baud, parity, data_bits, MAX_CHANNELS, logger)
        self._discovery.channel_found.connect(self._on_channel_found)
        self._discovery.progress.connect(self.discovery_progress.emit)
        self._discovery.finished.connect(self.discovery_finished.emit)

    def start_discovery(self):
        self._discovery.start(exclude_ports=self._claimed_ports)

    def disconnect_channel(self, address: int):
        """Manually release one channel - lets the user physically swap
        which module is wired to a shared adapter (one module out, the
        other in) and pick the new one up with a plain Scan, without
        restarting the app. The channel's card stays put (greyed out,
        not removed) - once a channel's been seen this session it stays
        visible, whether or not it's the one currently wired in. Does
        not touch the module's own power/output state - it's still
        whatever it was last set to.

        If this address was sharing its connection with another still-
        live address (two addresses asked on the same port via +Addr),
        the physical connection and port stay open for that other
        address - only actually closes/frees the port once nothing else
        is using it."""
        controller = self.controllers.get(address)
        if controller is None:
            return
        controller.cancel_pending()
        conn = self.connections.pop(address)
        self.controllers[address] = None
        port = self._address_port.pop(address, None)

        still_shared = any(
            self.connections.get(a) is conn and self.controllers.get(a) is not None
            for a in self.connections
        )
        if not still_shared:
            # conn.disconnect() first, port freed from _claimed_ports only
            # after it actually finishes - conn.disconnect() now processes
            # events internally while it waits for the reader thread to
            # stop (keeps the UI responsive), which means a Scan click
            # could land WHILE this is still running. If the port were
            # already marked free at that point, Scan could try to open
            # the exact same port the old thread hasn't finished
            # releasing yet - freeing it only after disconnect() returns
            # closes that window.
            conn.disconnect()
            if port:
                self._claimed_ports.discard(port)
            self._dispatch_wired.discard(id(conn))
        self.channel_offline.emit(address)

    def _connection_for_port(self, port: str) -> ConnectionController | None:
        for address, p in self._address_port.items():
            if p == port and self.controllers.get(address) is not None:
                return self.connections.get(address)
        return None

    def add_manual_channel(self, port: str, address: int):
        """Ask one address directly on one port - skips Scan's broadcast
        Address Query stage entirely, the same "just call the address"
        approach as the senior described. If that port already has a
        live channel on it (asking a second address on the one shared
        adapter you've actually got), reuses its existing connection
        instead of requiring it be disconnected first - responses get
        routed to the right channel by address (_dispatch_frame), so the
        two don't cross-talk. Retries a few times before giving up; on a
        real response, hands off to the exact same path a normal Scan
        uses, so it behaves identically either way (known address comes
        back online on its existing card, new one gets a fresh card)."""
        if self.controllers.get(address) is not None:
            self.command_timeout.emit(f"Address {address} is already connected.")
            return

        conn = self._connection_for_port(port)
        opened_new = conn is None
        if opened_new:
            baud = self.config.get("baud_rate", 115200)
            parity = self.config.get("parity", "N")
            data_bits = self.config.get("data_bits", 8)
            conn = ConnectionController()
            if not conn.connect(port, baud, parity, data_bits):
                self.command_timeout.emit(f"Failed to open {port}.")
                return

        timer = QTimer(self)
        timer.setSingleShot(True)
        attempts = {"count": 0}

        def on_raw_rx(data: bytes):
            # Logged even when nothing parses into a valid frame - tells
            # "truly nothing came back" apart from "something came back
            # but wasn't a legal response," which otherwise look
            # identical from the outside as one generic timeout.
            if self.logger:
                self.logger.info(f"Manual ask: raw bytes on {port}: {data.hex(' ').upper()}")

        def send_attempt():
            attempts["count"] += 1
            if self.logger:
                self.logger.info(
                    f"Manual ask: address {address} on {port} "
                    f"(attempt {attempts['count']}/{MANUAL_MAX_ATTEMPTS})"
                )
            conn.send(commands.query_status(address))
            timer.start(MANUAL_TIMEOUT_MS)

        def on_frame(frame: ParsedFrame):
            if frame.type != c.TYPE_STATUS_QUERY or frame.addr != address or len(frame.buf) < 6:
                return
            timer.stop()
            conn.frame_received.disconnect(on_frame)
            conn.raw_rx.disconnect(on_raw_rx)
            self._on_channel_found(port, address, conn, frame)

        def on_timeout():
            if attempts["count"] < MANUAL_MAX_ATTEMPTS:
                send_attempt()
                return
            conn.frame_received.disconnect(on_frame)
            conn.raw_rx.disconnect(on_raw_rx)
            if opened_new:
                # Only close it if this attempt opened it fresh - a
                # reused connection belongs to another still-live channel.
                conn.disconnect()
            msg = (
                f"No response from address {address} on {port} after "
                f"{MANUAL_MAX_ATTEMPTS} targeted attempts."
            )
            if self.logger:
                self.logger.warning(f"Manual ask: {msg}")
            self.command_timeout.emit(msg)

        timer.timeout.connect(on_timeout)
        conn.raw_rx.connect(on_raw_rx)
        conn.frame_received.connect(on_frame)
        send_attempt()

    def get_controller(self, address: int) -> ChannelController | None:
        return self.controllers[address]

    def get_state(self, address: int) -> ChannelState:
        return self.states[address]

    def save_all(self):
        for address, state in self.states.items():
            self.config.set_channel(address, {
                "last_level": state.data.last_level,
            })
        self.config.save()

    def turn_off_all(self):
        """Emergency stop: turn off every channel that's currently live -
        an offline channel (not the one physically wired in right now)
        has no connection to send anything over."""
        for controller in self.controllers.values():
            if controller is not None:
                controller.turn_output_off()

    def set_all_level(self, level: int):
        """Bulk action: set every currently-live channel to the same Level
        (L0-L3) at once. One command per channel, no intermediate values -
        the caller passes the final level directly, not a dragged range."""
        db = LEVEL_TO_DB[level]
        for address, controller in self.controllers.items():
            if controller is None:
                continue
            if db is None:
                controller.turn_output_off()
            elif self.states[address].data.output_on:
                controller.set_power(db)
            else:
                controller.resume_output(db)

    def shutdown(self):
        self._discovery.stop()
        # A shared port (two addresses asked on one connection) means
        # self.connections can hold the same object twice - dedupe by
        # identity so disconnect() isn't called on it more than once.
        seen = {id(conn): conn for conn in self.connections.values()}
        for conn in seen.values():
            conn.disconnect()

    def _dispatch_frame(self, frame: ParsedFrame):
        # Needed once a connection can be shared by more than one address
        # (+Addr reusing a port) - a direct connect(controller.handle_frame)
        # would hand EVERY frame on that connection to EVERY address
        # sharing it, corrupting whichever one didn't actually send it.
        controller = self.controllers.get(frame.addr)
        if controller is not None:
            controller.handle_frame(frame)

    def _on_channel_found(self, port: str, address: int, conn: ConnectionController, initial_frame: ParsedFrame):
        if self.controllers.get(address) is not None:
            # Two modules reporting the same address at once (e.g. both
            # still at factory default) - already have one live, so
            # release this redundant connection rather than silently
            # overwriting it.
            if self.logger:
                self.logger.warning(
                    f"Discovery: {port} reports address {address}, already in use by another port - skipping."
                )
            conn.disconnect()
            return

        returning = address in self.states
        if returning:
            # A known channel physically swapped back in - reuse its
            # existing state (and card) rather than treating it as new.
            state = self.states[address]
        else:
            state = ChannelState(address)
            saved = self.config.get_channel(address)
            if saved and "last_level" in saved:
                state.data.last_level = saved["last_level"]

        controller = ChannelController(conn, state, self.logger)
        controller.command_timeout.connect(self.command_timeout.emit)
        if id(conn) not in self._dispatch_wired:
            conn.frame_received.connect(self._dispatch_frame)
            self._dispatch_wired.add(id(conn))
        conn.raw_tx.connect(lambda data, addr=address: self.raw_tx.emit(addr, data))
        conn.raw_rx.connect(lambda data, addr=address: self.raw_rx.emit(addr, data))

        self.states[address] = state
        self.controllers[address] = controller
        self.connections[address] = conn
        self._claimed_ports.add(port)
        self._address_port[address] = port

        # Seed from the discovery frame itself - it's the exact same
        # Status Query response the doc's plan asks for, no need to send
        # a second, redundant one right after finding the channel.
        controller.handle_frame(initial_frame)

        self.channel_online.emit(address) if returning else self.channel_added.emit(address)
