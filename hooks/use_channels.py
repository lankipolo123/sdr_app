from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState
from state.level_map import LEVEL_TO_DB
from .use_channel import ChannelController
from .use_connection import ConnectionController
from .use_discovery import DiscoveryController

MANUAL_TIMEOUT_MS = 800

MAX_CHANNELS = 16  # ceiling on how many ports we'll ever probe at once


class ChannelManager(QObject):
    """Owns one dedicated ConnectionController per discovered channel -
    unlike the old shared-bus design, each module has its own serial
    port (RS422 is point-to-point, not a shared bus), so there's no
    single connection to route frames through anymore. Each port's
    frame_received is wired directly to that port's own
    ChannelController."""

    channel_added = Signal(int)          # address
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
        self._port_connections: dict[str, ConnectionController] = {}
        self._manual_probes: dict[str, tuple] = {}  # port -> (address, timer, handler)

        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)
        self._discovery = DiscoveryController(baud, parity, data_bits, MAX_CHANNELS, logger)
        self._discovery.channel_found.connect(self._on_channel_found)
        self._discovery.progress.connect(self.discovery_progress.emit)
        self._discovery.finished.connect(self.discovery_finished.emit)

    def start_discovery(self):
        self._discovery.start(exclude_ports=self._claimed_ports)

    def add_manual_channel(self, port: str, address: int):
        """Targeted add: sends a Status Query straight to one address on
        one port - never a broadcast. Reuses the port's existing
        connection if one's already open (this is the only path that
        lets two addresses share a single port), so this is also how a
        second module on the same shared converter gets tried without
        touching the first channel's connection."""
        if address in self.states:
            self.command_timeout.emit(f"Address {address} is already connected.")
            return
        if port in self._manual_probes:
            return  # a probe on this port is already in flight

        conn = self._port_connections.get(port)
        opened_new = conn is None
        if opened_new:
            baud = self.config.get("baud_rate", 115200)
            parity = self.config.get("parity", "N")
            data_bits = self.config.get("data_bits", 8)
            conn = ConnectionController()
            if not conn.connect(port, baud, parity, data_bits):
                return
            conn.frame_received.connect(self._dispatch_frame)
            self._port_connections[port] = conn

        timer = QTimer(self)
        timer.setSingleShot(True)

        def on_frame(frame: ParsedFrame):
            if frame.type != c.TYPE_STATUS_QUERY or frame.addr != address or len(frame.buf) < 6:
                return
            timer.stop()
            conn.frame_received.disconnect(on_frame)
            del self._manual_probes[port]
            self._finish_manual_add(port, address, conn, frame)

        def on_timeout():
            conn.frame_received.disconnect(on_frame)
            del self._manual_probes[port]
            if opened_new:
                del self._port_connections[port]
                conn.disconnect()
            msg = f"No response from address {address} on {port} (targeted query, no broadcast)."
            if self.logger:
                self.logger.warning(f"Manual add: {msg}")
            self.command_timeout.emit(msg)

        timer.timeout.connect(on_timeout)
        conn.frame_received.connect(on_frame)
        self._manual_probes[port] = (address, timer, on_frame)
        conn.send(commands.query_status(address))
        timer.start(MANUAL_TIMEOUT_MS)

    def _finish_manual_add(self, port: str, address: int, conn: ConnectionController, frame: ParsedFrame):
        state = ChannelState(address)
        saved = self.config.get_channel(address)
        if saved and "last_level" in saved:
            state.data.last_level = saved["last_level"]

        controller = ChannelController(conn, state, self.logger)
        controller.command_timeout.connect(self.command_timeout.emit)
        conn.raw_tx.connect(lambda data, addr=address: self.raw_tx.emit(addr, data))
        conn.raw_rx.connect(lambda data, addr=address: self.raw_rx.emit(addr, data))

        self.states[address] = state
        self.controllers[address] = controller
        self.connections[address] = conn
        self._claimed_ports.add(port)

        controller.handle_frame(frame)
        self.channel_added.emit(address)

    def _dispatch_frame(self, frame: ParsedFrame):
        controller = self.controllers.get(frame.addr)
        if controller:
            controller.handle_frame(frame)

    def get_controller(self, address: int) -> ChannelController:
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
        """Emergency stop: turn every discovered channel's output off."""
        for controller in self.controllers.values():
            controller.turn_output_off()

    def set_all_level(self, level: int):
        """Bulk action: set every discovered channel to the same Level
        (L0-L3) at once. One command per channel, no intermediate values -
        the caller passes the final level directly, not a dragged range."""
        db = LEVEL_TO_DB[level]
        for address, controller in self.controllers.items():
            if db is None:
                controller.turn_output_off()
            elif self.states[address].data.output_on:
                controller.set_power(db)
            else:
                controller.resume_output(db)

    def shutdown(self):
        self._discovery.stop()
        # A shared port (two manually-added addresses on one connection)
        # means self.connections can hold the same object twice - dedupe
        # by identity so disconnect() isn't called on it twice.
        seen = {id(conn): conn for conn in self.connections.values()}
        for conn in seen.values():
            conn.disconnect()

    def _on_channel_found(self, port: str, address: int, conn: ConnectionController, initial_frame: ParsedFrame):
        if address in self.states:
            # Two modules reporting the same address (e.g. both still at
            # factory default) - already have one, so release this
            # redundant connection rather than silently overwriting it.
            if self.logger:
                self.logger.warning(
                    f"Discovery: {port} reports address {address}, already in use by another port - skipping."
                )
            conn.disconnect()
            return

        state = ChannelState(address)
        saved = self.config.get_channel(address)
        if saved and "last_level" in saved:
            state.data.last_level = saved["last_level"]

        controller = ChannelController(conn, state, self.logger)
        controller.command_timeout.connect(self.command_timeout.emit)
        conn.frame_received.connect(self._dispatch_frame)
        conn.raw_tx.connect(lambda data, addr=address: self.raw_tx.emit(addr, data))
        conn.raw_rx.connect(lambda data, addr=address: self.raw_rx.emit(addr, data))

        self.states[address] = state
        self.controllers[address] = controller
        self.connections[address] = conn
        self._claimed_ports.add(port)
        self._port_connections[port] = conn

        # Seed from the discovery frame itself - it's the exact same
        # Status Query response the doc's plan asks for, no need to send
        # a second, redundant one right after finding the channel.
        controller.handle_frame(initial_frame)

        self.channel_added.emit(address)
