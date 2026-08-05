import struct
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState

RESPONSE_TIMEOUT_MS = 2000


class ChannelController(QObject):
    """Handles commands + responses for one addressed channel, over its
    own dedicated ConnectionController."""

    command_timeout = Signal(str)

    def __init__(self, connection_controller, state: ChannelState, logger=None):
        super().__init__()
        self.conn = connection_controller
        self.state = state
        self.logger = logger
        self._pending_timer: QTimer | None = None
        self._pending_label = None
        self._pending_state_update: dict | None = None
        self._queue: deque = deque()  # commands waiting for the in-flight one to finish

    @property
    def address(self) -> int:
        return self.state.data.address

    @property
    def display_name(self) -> str:
        # Matches ChannelCard's own title exactly (f"CH{display_number:02d}")
        # - any message shown to the user has to use this, never the raw
        # protocol address, or it won't match the card it's about.
        return f"CH{self.state.display_number:02d}"

    def turn_output_on(self):
        self._enqueue(commands.output_on(self.address), "Output ON", {"output_on": True})

    def turn_output_off(self):
        self._enqueue(commands.output_off(self.address), "Output OFF", {"output_on": False})

    def set_power(self, power_db: int):
        """Resend Signal Control with this channel's own stored Mode/
        Frequency/Bandwidth unchanged, plus the new Power value - the only
        field the customer can actually change. Requires a prior Status
        Query response (discovery seeds this); if we somehow don't have a
        baseline yet, we refuse rather than invent Frequency/Bandwidth."""
        d = self.state.data
        if d.mode is None or d.frequency_mhz is None or d.bandwidth_mhz is None:
            msg = (
                f"{self.display_name}: no status baseline yet - "
                f"can't apply power={power_db}dB without a Status Query first."
            )
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)
            return

        frame = commands.set_signal(self.address, d.mode, d.frequency_mhz, d.bandwidth_mhz, power_db)
        self._enqueue(frame, f"Power -> {power_db}dB", {"power_db": power_db, "output_on": True})

    def resume_output(self, power_db: int):
        """Turning back on after being off needs an explicit Output Switch
        ON, not just a Signal Control power change - confirmed on real
        hardware (spectrum analyzer) that RF power never actually comes
        back up from Signal Control alone once the module's been switched
        off, even though the app's own ack-driven state made it *look*
        like it turned back on. Output Switch ON is queued first so it's
        acknowledged before Signal Control goes out."""
        self.turn_output_on()
        self.set_power(power_db)

    def read_status(self):
        self._enqueue(commands.query_status(self.address), "Status query")

    def _enqueue(self, frame: bytes, label: str, state_update: dict | None = None):
        self._queue.append((frame, label, state_update))
        if self._pending_timer is None:
            self._send_next()

    def _send_next(self):
        if not self._queue:
            return
        frame, label, state_update = self._queue.popleft()
        self._send(frame, label, state_update)

    def _send(self, frame: bytes, label: str, state_update: dict | None = None):
        # Deliberately does NOT call state.update() here - only a confirmed
        # response (handle_frame) should trigger the state's `changed`
        # signal, or the UI would resync from stale hardware state and
        # visibly snap the slider back before the real ack arrives.
        if self.logger:
            self.logger.info(f"TX ch{self.address} ({label}): {frame.hex(' ').upper()}")

        sent = self.conn.send(frame)
        if not sent:
            self._send_next()  # this one failed to even go out - move on rather than stall the queue
            return

        self._pending_label = label
        self._pending_state_update = state_update
        self._pending_timer = QTimer()
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(self._on_response_timeout)
        self._pending_timer.start(RESPONSE_TIMEOUT_MS)

    def _cancel_pending_timeout(self):
        if self._pending_timer is not None:
            self._pending_timer.stop()
            self._pending_timer = None
            self._pending_label = None
            self._pending_state_update = None

    def cancel_pending(self):
        """Call when this controller's connection is being torn down (e.g.
        manual disconnect for a physical module swap) while a command may
        still be in flight - without this, an already-running response
        timer keeps ticking on an object nothing else references anymore,
        and fires a misleading "no response" warning later, possibly
        after this same address is already back online under a fresh
        controller."""
        self._cancel_pending_timeout()
        self._queue.clear()

    def _on_response_timeout(self):
        msg = (
            f"{self.display_name}: no response within {RESPONSE_TIMEOUT_MS}ms "
            f"for: {self._pending_label}"
        )
        if self.logger:
            self.logger.warning(msg)
        self.command_timeout.emit(msg)
        self._pending_timer = None
        self._pending_label = None
        self._send_next()

    def handle_frame(self, frame: ParsedFrame):
        """Called by ChannelManager only for frames whose addr matches ours."""
        pending_update = self._pending_state_update
        self._cancel_pending_timeout()
        if self.logger:
            self.logger.info(f"RX ch{self.address}: {frame.raw.hex(' ').upper()} -> {frame.describe()}")

        if frame.type in (c.TYPE_OUTPUT_SWITCH, c.TYPE_SIGNAL_CONTROL) and len(frame.buf) == 1:
            if frame.buf[0] == c.RESP_SUCCESS and pending_update:
                self.state.update(**pending_update)
            self._send_next()
        elif frame.type == c.TYPE_STATUS_QUERY and len(frame.buf) >= 6:
            output = frame.buf[0]
            mode = frame.buf[1]
            freq = struct.unpack(">H", frame.buf[2:4])[0]
            bw_code = frame.buf[4]
            pw_code = frame.buf[5]
            self.state.update(
                output_on=bool(output),
                mode=mode,
                frequency_mhz=freq,
                bandwidth_mhz=c.BANDWIDTH_CODES_REV.get(bw_code),
                power_db=c.POWER_CODES_REV.get(pw_code),
            )
            self._send_next()
