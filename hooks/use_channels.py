from PySide6.QtCore import QObject, Signal

from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState
from state.level_map import LEVEL_TO_DB
from .use_channel import ChannelController
from .use_connection import ConnectionController
from .use_discovery import DiscoveryController

MAX_CHANNELS = 16  # ceiling on how many ports we'll ever probe at once


class ChannelManager(QObject):
    """Owns one dedicated ConnectionController per discovered channel -
    unlike the old shared-bus design, each module has its own serial
    port (RS422 is point-to-point, not a shared bus), so there's no
    single connection to route frames through anymore. Each port's
    frame_received is wired directly to that port's own
    ChannelController."""

    channel_added = Signal(int)          # address
    channel_removed = Signal(int)        # address
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
        """Manually release one channel and free its port - lets the user
        physically swap which module is wired to a shared adapter (one
        module out, the other in) and pick the new one up with a plain
        Scan, without restarting the app. Does not touch the module's own
        power/output state - it's still whatever it was last set to."""
        if address not in self.states:
            return
        conn = self.connections.pop(address)
        self.controllers.pop(address)
        self.states.pop(address)
        port = self._address_port.pop(address, None)
        if port:
            self._claimed_ports.discard(port)
        conn.disconnect()
        self.channel_removed.emit(address)

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
        for conn in self.connections.values():
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
        conn.frame_received.connect(controller.handle_frame)
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

        self.channel_added.emit(address)
