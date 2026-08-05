from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal

from .level_map import DEFAULT_RESUME_LEVEL


@dataclass
class ChannelStateData:
    address: int                     # real protocol address (0-based) - never shown in UI
    output_on: bool = False
    mode: int | None = None          # populated from Status Query, echoed back unchanged
    frequency_mhz: int | None = None
    bandwidth_mhz: int | None = None
    power_db: int | None = None
    last_level: int = DEFAULT_RESUME_LEVEL  # slider position to resume to on toggle-on


class ChannelState(QObject):
    """One instance per discovered hardware channel. The old app had a
    single global DeviceState for the one device it talked to; this app
    talks to many addressed channels on the same serial bus, so each one
    gets its own state + its own 'changed' signal."""

    changed = Signal()

    def __init__(self, address: int):
        super().__init__()
        self.data = ChannelStateData(address=address)

    @property
    def display_number(self) -> int:
        # CHn's n IS the address, always, everywhere - no +1 offset. Two
        # different numbers for the same channel is exactly what caused
        # "Channel 2" (a warning using the raw address) to look like a
        # different, missing channel from "CH03" (the card, which used to
        # add 1) - removing the offset entirely means there's no second
        # numbering scheme left to drift out of sync with the first.
        return self.data.address

    def update(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self.data, k, v)
        self.changed.emit()
