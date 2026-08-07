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
    power_code: int | None = None    # raw hex byte last confirmed on the wire
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
        # The one and only place the UI-facing channel number is
        # computed - CH01..CH16 for internal addresses 0..15. Every
        # user-facing label (card title, command_timeout messages) goes
        # through this same property/display_name, so there's still
        # only one numbering scheme to stay in sync - it just now
        # starts at 1 instead of matching the raw address directly.
        return self.data.address + 1

    def update(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self.data, k, v)
        self.changed.emit()
