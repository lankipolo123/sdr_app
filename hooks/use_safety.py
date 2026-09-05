from utils.signal import Signal
from .use_channels import MAX_CHANNELS

# Confirmed threshold, manual-reset-only (matches the C rewrite): once
# tripped it stays tripped until the user explicitly resets it, rather
# than silently re-enabling the instant the reading dips back under the
# line - that would let it cycle on/off right at the boundary, and would
# make the safety trivially self-defeating (turn a channel back on, it
# trips again next reading, forever).
KILL_SWITCH_THRESHOLD_C = 60.0


class SafetyController:
    """Amplifier-overtemperature interlock: force every channel off the
    moment the sensor reports >= KILL_SWITCH_THRESHOLD_C, and refuse to
    let anything power back on until a human explicitly resets it."""

    def __init__(self, channels, logger=None):
        self.channels = channels
        self.logger = logger
        self.tripped_changed = Signal()
        self.tripped = False

    def on_sensor_state(self, state: dict) -> None:
        if self.tripped:
            return
        if state.get("has_reading") and state.get("temperature_c", 0.0) >= KILL_SWITCH_THRESHOLD_C:
            self._trip(state["temperature_c"])

    def _trip(self, temperature_c: float) -> None:
        self.tripped = True
        if self.logger:
            self.logger.warning(
                f"KILL SWITCH: amplifier temperature {temperature_c:.1f} C >= "
                f"{KILL_SWITCH_THRESHOLD_C:.0f} C - forcing all channels OFF"
            )
        for address in range(MAX_CHANNELS):
            self.channels.get_controller(address).turn_output_off()
        self.tripped_changed.emit(True)

    def reset(self) -> None:
        if not self.tripped:
            return
        self.tripped = False
        if self.logger:
            self.logger.info("KILL SWITCH: reset by user")
        self.tripped_changed.emit(False)

    def allow_power_on(self) -> bool:
        """Gate for anything that would turn a channel on or raise its
        level - OFF/level-0 is never gated, same reasoning as the C
        rewrite (a safety trip must never block turning something OFF,
        and OFF is never how you'd defeat the trip)."""
        return not self.tripped
