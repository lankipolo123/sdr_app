from PySide6.QtCore import QObject, Signal

# Confirmed threshold, manual-reset-only (matches the C rewrite and
# sdr_react): once tripped it stays tripped until a human explicitly
# resets it, rather than silently re-enabling the instant the reading
# dips back under the line - that would let it cycle on/off right at
# the boundary, and would make the safety trivially self-defeating
# (turn a channel back on, it trips again next reading, forever).
KILL_SWITCH_THRESHOLD_C = 60.0


class SafetyController(QObject):
    """Amplifier-overtemperature interlock: force every channel off the
    moment the sensors' rack-wide average reading crosses
    KILL_SWITCH_THRESHOLD_C - same "average across every unit that has a
    real reading" source as the C rewrite's check_kill_switch(). Trip
    state is tracked per channel (not one rack-wide flag): an automatic
    or manual trip marks every channel tripped together, but each can be
    reset independently afterward, same as the C rewrite's
    on_unit_kill_reset()."""

    changed = Signal()  # tripped-set changed - re-read tripped_addresses()

    def __init__(self, channel_manager):
        super().__init__()
        self.channel_manager = channel_manager
        self._tripped: set[int] = set()

    def tripped_addresses(self) -> list[int]:
        return sorted(self._tripped)

    def is_tripped(self, address: int) -> bool:
        return address in self._tripped

    def on_sensor_reading(self, avg_temperature_c: float | None):
        if avg_temperature_c is None or avg_temperature_c < KILL_SWITCH_THRESHOLD_C:
            return
        self._trip_all()

    def manual_trip_all(self):
        """Same rack-wide effect as an automatic overtemp trip (see the
        C rewrite's on_kill_switch_manual_trip()), for testing without
        needing the average to actually cross KILL_SWITCH_THRESHOLD_C."""
        self._trip_all()

    def _trip_all(self):
        changed = False
        for address in range(len(self.channel_manager.controllers)):
            if address not in self._tripped:
                self._tripped.add(address)
                self.channel_manager.get_controller(address).turn_output_off()
                changed = True
        if changed:
            self.changed.emit()

    def reset_all(self):
        if not self._tripped:
            return
        self._tripped.clear()
        self.changed.emit()

    def reset_one(self, address: int):
        """Per-unit reset - resets just this one channel, independent of
        the others (see the C rewrite's on_unit_kill_reset())."""
        if address not in self._tripped:
            return
        self._tripped.discard(address)
        self.changed.emit()

    def allow_power_on(self, address: int) -> bool:
        """Gate for anything that would turn a channel on or raise its
        level - OFF/level-0 is never gated, same reasoning as the C
        rewrite and sdr_react (a safety trip must never block turning
        something OFF, and OFF is never how you'd defeat the trip).
        Per-channel: a channel that's been individually reset can power
        back on even while others stay tripped."""
        return address not in self._tripped
