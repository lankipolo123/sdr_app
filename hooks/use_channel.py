import struct

from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState

RESPONSE_TIMEOUT_MS = 2000


class ChannelController(QObject):
    """Handles commands + responses for exactly one addressed channel.

    Shares one ConnectionController (one serial link) with every other
    channel on the bus - ChannelManager routes incoming frames to the
    right ChannelController by address.

    Unlike the old DeviceController, this has no query_address()/
    set_address() (no Module Address UI at all) and no
    apply_signal_settings() with user-chosen Mode/Frequency/Bandwidth -
    the customer can only change Power, via set_power(). Mode/Frequency/
    Bandwidth are always the values last read from the module itself.
    """

    command_timeout = Signal(str)

    def __init__(self, connection_controller, state: ChannelState, logger=None):
        super().__init__()
        self.conn = connection_controller
        self.state = state
        self.logger = logger
        self._pending_timer: QTimer | None = None
        self._pending_label = None
        self._pending_state_update: dict | None = None

    @property
    def address(self) -> int:
        return self.state.data.address

    def turn_output_on(self):
        self._send(commands.output_on(self.address), "Output ON", {"output_on": True})

    def turn_output_off(self):
        self._send(commands.output_off(self.address), "Output OFF", {"output_on": False})

    def set_power(self, power_db: int):
        """Resend Signal Control with this channel's own stored Mode/
        Frequency/Bandwidth unchanged, plus the new Power value - the only
        field the customer can actually change. Requires a prior Status
        Query response (discovery seeds this); if we somehow don't have a
        baseline yet, we refuse rather than invent Frequency/Bandwidth."""
        d = self.state.data
        if d.mode is None or d.frequency_mhz is None or d.bandwidth_mhz is None:
            msg = (
                f"Channel {self.address}: no status baseline yet - "
                f"can't apply power={power_db}dB without a Status Query first."
            )
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)
            return

        frame = commands.set_signal(self.address, d.mode, d.frequency_mhz, d.bandwidth_mhz, power_db)
        self._send(frame, f"Power -> {power_db}dB", {"power_db": power_db, "output_on": True})

    def read_status(self):
        self._send(commands.query_status(self.address), "Status query")

    def _send(self, frame: bytes, label: str, state_update: dict | None = None):
        # Deliberately does NOT call state.update() here - only a confirmed
        # response (handle_frame) should trigger the state's `changed`
        # signal, or the UI would resync from stale hardware state and
        # visibly snap the slider back before the real ack arrives.
        if self.logger:
            self.logger.info(f"TX ch{self.address} ({label}): {frame.hex(' ').upper()}")

        sent = self.conn.send(frame)
        if not sent:
            return

        self._cancel_pending_timeout()
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

    def _on_response_timeout(self):
        msg = (
            f"Channel {self.address}: no response within {RESPONSE_TIMEOUT_MS}ms "
            f"for: {self._pending_label}"
        )
        if self.logger:
            self.logger.warning(msg)
        self.command_timeout.emit(msg)
        self._pending_timer = None
        self._pending_label = None

    def handle_frame(self, frame: ParsedFrame):
        """Called by ChannelManager only for frames whose addr matches ours."""
        pending_update = self._pending_state_update
        self._cancel_pending_timeout()
        if self.logger:
            self.logger.info(f"RX ch{self.address}: {frame.raw.hex(' ').upper()} -> {frame.describe()}")

        if frame.type in (c.TYPE_OUTPUT_SWITCH, c.TYPE_SIGNAL_CONTROL) and len(frame.buf) == 1:
            if frame.buf[0] == c.RESP_SUCCESS and pending_update:
                self.state.update(**pending_update)
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
