import time
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal

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
    # Cumulative ON-time, in seconds, accumulated BEFORE the channel's
    # current ON period (or the whole total, while it's off) - an
    # odometer, not an app-uptime counter. See ChannelState's
    # current_uptime_seconds()/_on_since for the live-tracking half of
    # this, direct port of the C rewrite's
    # g_channel_uptime_base_seconds/g_channel_on_since_ms.
    uptime_base_seconds: float = 0.0


class ChannelState(QObject):

    changed = Signal()

    def __init__(self, address: int):
        super().__init__()
        self.data = ChannelStateData(address=address)
        self._on_since: float | None = None

    @property
    def display_number(self) -> int:
        return self.data.address + 1

    def init_uptime_tracking(self):
        """Call once, after any saved fields (including output_on) have
        been applied directly to self.data at construction - see
        ChannelManager._make_state(). A channel restored as already ON
        starts a fresh ON period timed from app launch (the app has no
        way to know how long it was ON while it wasn't running, so that
        gap isn't credited - only time the app actually tracked ever
        counts), same behavior as the C rewrite's first WM_TIMER tick
        after startup."""
        self._on_since = time.monotonic() if self.data.output_on else None

    def current_uptime_seconds(self) -> float:
        live = (time.monotonic() - self._on_since) if self._on_since is not None else 0.0
        return self.data.uptime_base_seconds + live

    def update(self, **kwargs):
        if "output_on" in kwargs and kwargs["output_on"] != self.data.output_on:
            if kwargs["output_on"]:
                self._on_since = time.monotonic()
            elif self._on_since is not None:
                self.data.uptime_base_seconds += time.monotonic() - self._on_since
                self._on_since = None
        for k, v in kwargs.items():
            setattr(self.data, k, v)
        self.changed.emit()
