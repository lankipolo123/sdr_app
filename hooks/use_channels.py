from PySide6.QtCore import QObject, Signal

from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState
from state.level_map import LEVEL_TO_DB
from .use_channel import ChannelController
from .use_discovery import DiscoveryController

MAX_CHANNELS = 16  # UI/practicality ceiling - protocol/constants.py ADDR_MAX is actually 199


class ChannelManager(QObject):
    channel_added = Signal(int)          # address
    discovery_progress = Signal(int, int)
    discovery_finished = Signal()
    command_timeout = Signal(str)

    def __init__(self, connection_controller, config_service, logger=None):
        super().__init__()
        self.conn = connection_controller
        self.config = config_service
        self.logger = logger
        self.states: dict[int, ChannelState] = {}
        self.controllers: dict[int, ChannelController] = {}

        # Listens for every frame regardless of discovery state, so that
        # a Status Query answer routes to the right channel even after
        # discovery has finished (e.g. hardware-side state changes).
        self.conn.frame_received.connect(self._route_frame)

        self._discovery = DiscoveryController(self.conn, MAX_CHANNELS, logger)
        self._discovery.channel_found.connect(self._on_channel_found)
        self._discovery.progress.connect(self.discovery_progress.emit)
        self._discovery.finished.connect(self.discovery_finished.emit)

    def start_discovery(self):
        self._discovery.start()

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
        for controller in self.controllers.values():
            if db is None:
                controller.turn_output_off()
            else:
                controller.set_power(db)

    def _on_channel_found(self, address: int, initial_frame: ParsedFrame):
        if address in self.states:
            return

        state = ChannelState(address)
        saved = self.config.get_channel(address)
        if saved and "last_level" in saved:
            state.data.last_level = saved["last_level"]

        controller = ChannelController(self.conn, state, self.logger)
        controller.command_timeout.connect(self.command_timeout.emit)

        self.states[address] = state
        self.controllers[address] = controller

        # Seed from the discovery frame itself - it's the exact same
        # Status Query response the doc's plan asks for, no need to send
        # a second, redundant one right after finding the channel.
        controller.handle_frame(initial_frame)

        self.channel_added.emit(address)

    def _route_frame(self, frame: ParsedFrame):
        controller = self.controllers.get(frame.addr)
        if controller is not None:
            controller.handle_frame(frame)
