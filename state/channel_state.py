from dataclasses import dataclass

from utils.signal import Signal

from .level_map import DEFAULT_RESUME_LEVEL


@dataclass
class ChannelStateData:
    address: int
    output_on: bool = False
    mode: int | None = None
    frequency_mhz: int | None = None
    bandwidth_mhz: int | None = None
    power_code: int | None = None
    last_level: int = DEFAULT_RESUME_LEVEL


class ChannelState:

    def __init__(self, address: int):
        self.changed = Signal()
        self.data = ChannelStateData(address=address)

    @property
    def display_number(self) -> int:
        return self.data.address + 1

    def update(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self.data, k, v)
        self.changed.emit()
