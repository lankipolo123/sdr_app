from PySide6.QtCore import QObject, Signal

from state.channel_state import ChannelState
from .use_channel import ChannelController

MAX_CHANNELS = 16  # ceiling on how many addresses the UI shows cards for


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

        self.states: dict[int, ChannelState] = {}
        self.controllers: dict[int, ChannelController] = {}
        for address in range(MAX_CHANNELS):
            state = self._make_state(address)
            controller = ChannelController(state, baud, parity, data_bits, self.logger)
            controller.command_timeout.connect(self.command_timeout.emit)
            self.states[address] = state
            self.controllers[address] = controller

    def _make_state(self, address: int) -> ChannelState:
        state = ChannelState(address)
        saved = self.config.get_channel(address)
        if saved and "last_level" in saved:
            state.data.last_level = saved["last_level"]
        return state

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

    def shutdown(self):
        for controller in self.controllers.values():
            controller.cancel_pending()
