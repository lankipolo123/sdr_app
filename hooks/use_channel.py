import struct
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame
from state.channel_state import ChannelState
from .use_connection import ConnectionController

RESPONSE_TIMEOUT_MS = 800
# Collision on a shared line is probabilistic, not a hard 100% wall -
# confirmed on real hardware: some attempts get a clean response even
# with two modules wired in, others don't. Retrying several times
# before giving up meaningfully improves the odds of getting through,
# instead of reporting failure after a single unlucky attempt. Matches
# the already-proven MANUAL_MAX_ATTEMPTS pattern used by +Addr.
RETRY_MAX_ATTEMPTS = 6


class ChannelController(QObject):
    """Handles commands + responses for one addressed channel. Each
    command brute-force finds an available port and opens its own
    connection fresh (see _find_and_open_connection), rather than
    keeping one connection open persistently for the whole time the
    channel is "online" - matches the reference tool's own actual
    behavior (find the port, send, per button press), and means the
    port is never held open between commands, so other addresses on a
    shared adapter can use it too."""

    command_timeout = Signal(str)

    def __init__(self, state: ChannelState, baud: int = 115200, parity: str = "N",
                 data_bits: int = 8, logger=None, preferred_port: str | None = None):
        super().__init__()
        self.state = state
        self.baud = baud
        self.parity = parity
        self.data_bits = data_bits
        self.logger = logger
        # The port this channel was actually discovered on - tried first
        # on every command before falling back to searching every other
        # available port. Without this, "just grab whichever port opens
        # first" would be wrong the moment more than one physical port
        # is in play (e.g. two modules on two separate adapters) - it
        # could send address 0's command out a port that only ever had
        # address 1's module on it, which would simply never answer.
        self.preferred_port = preferred_port
        self._temp_conn: ConnectionController | None = None
        self._pending_timer: QTimer | None = None
        self._pending_label = None
        self._pending_state_update: dict | None = None
        self._pending_frame: bytes | None = None
        self._pending_attempt = 0
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

    def set_power(self, power_code: int):
        """Resend Signal Control with this channel's own stored Mode/
        Frequency/Bandwidth unchanged, plus the new Power value - the only
        field the customer can actually change. Requires a prior Status
        Query response (discovery seeds this); if we somehow don't have a
        baseline yet, we refuse rather than invent Frequency/Bandwidth."""
        d = self.state.data
        if d.mode is None or d.frequency_mhz is None or d.bandwidth_mhz is None:
            msg = (
                f"{self.display_name}: no status baseline yet - "
                f"can't apply power_code=0x{power_code:02X} without a Status Query first."
            )
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)
            return

        # Only power_code - NOT output_on. Signal Control doesn't reliably
        # indicate output state on its own (see resume_output()'s own
        # comment: it reconfigures parameters but doesn't re-enable the
        # RF stage by itself). Asserting output_on=True here used to be
        # harmless when called on an already-on channel, but wrong when
        # called as the second half of resume_output() and the FIRST
        # command (turn_output_on) got rejected or timed out - this one
        # succeeding would silently flip output_on back to True right
        # after the timeout/rejection path had just correctly reverted
        # it to False. turn_output_on()'s own state_update is the only
        # thing that should ever claim output_on=True.
        frame = commands.set_signal(self.address, d.mode, d.frequency_mhz, d.bandwidth_mhz, power_code)
        self._enqueue(frame, f"Power -> 0x{power_code:02X}", {"power_code": power_code})

    def resume_output(self, power_code: int):
        """Turning back on after being off needs an explicit Output Switch
        ON, not just a Signal Control power change - confirmed on real
        hardware (spectrum analyzer) that RF power never actually comes
        back up from Signal Control alone once the module's been switched
        off, even though the app's own ack-driven state made it *look*
        like it turned back on. Output Switch ON is queued first so it's
        acknowledged before Signal Control goes out."""
        self.turn_output_on()
        self.set_power(power_code)

    def read_status(self):
        self._enqueue(commands.query_status(self.address), "Status query")

    def _enqueue(self, frame: bytes, label: str, state_update: dict | None = None):
        self._queue.append((frame, label, state_update))
        if self._pending_timer is None and self._temp_conn is None:
            self._send_next()

    def _send_next(self):
        if not self._queue:
            return
        frame, label, state_update = self._queue.popleft()
        self._pending_attempt = 0
        self._open_and_send(frame, label, state_update)

    def _open_and_send(self, frame: bytes, label: str, state_update: dict | None):
        # Brute-force find a port fresh for this command - try every
        # currently available port until one opens, same "just find one
        # that works" spirit as the reference tool's button-press
        # behavior. Reused across this command's own retries (not
        # re-found every retry), closed once the command finishes
        # (confirmed, rejected, or retries
        # exhausted).
        conn = self._find_and_open_connection()
        if conn is None:
            if self.logger:
                self.logger.warning(f"TX ch{self.address} ({label}): no port opened successfully.")
            self._pending_frame = frame
            self._pending_label = label
            self._pending_state_update = state_update
            self._on_response_timeout()  # feeds the same retry/give-up logic as an unanswered send
            return

        self._temp_conn = conn
        conn.frame_received.connect(self._on_frame_received)
        self._send(frame, label, state_update)

    def _find_and_open_connection(self) -> ConnectionController | None:
        ports = ConnectionController.list_ports()
        if self.preferred_port in ports:
            ports = [self.preferred_port] + [p for p in ports if p != self.preferred_port]
        for port in ports:
            conn = ConnectionController()
            if conn.connect(port, self.baud, self.parity, self.data_bits):
                return conn
        return None

    def _send(self, frame: bytes, label: str, state_update: dict | None = None):
        # Deliberately does NOT call state.update() here - only a confirmed
        # response (handle_frame) should trigger the state's `changed`
        # signal, or the UI would resync from stale hardware state and
        # visibly snap the slider back before the real ack arrives.
        if self.logger:
            attempt_note = f" (attempt {self._pending_attempt + 1}/{RETRY_MAX_ATTEMPTS})" if self._pending_attempt else ""
            self.logger.info(f"TX ch{self.address} ({label}){attempt_note}: {frame.hex(' ').upper()}")

        sent = self._temp_conn.send(frame)
        if not sent:
            self._close_temp_conn()
            self._send_next()  # this one failed to even go out - move on rather than stall the queue
            return

        self._pending_frame = frame
        self._pending_label = label
        self._pending_state_update = state_update
        self._pending_timer = QTimer()
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(self._on_response_timeout)
        self._pending_timer.start(RESPONSE_TIMEOUT_MS)

    def _close_temp_conn(self):
        if self._temp_conn is not None:
            try:
                self._temp_conn.frame_received.disconnect(self._on_frame_received)
            except (TypeError, RuntimeError):
                pass
            self._temp_conn.disconnect()
            self._temp_conn = None

    def _on_frame_received(self, frame: ParsedFrame):
        if frame.addr != self.address:
            return  # not addressed to us - stray traffic, ignore
        self.handle_frame(frame)

    def _cancel_pending_timeout(self):
        if self._pending_timer is not None:
            self._pending_timer.stop()
            self._pending_timer = None
        self._pending_label = None
        self._pending_state_update = None
        self._pending_frame = None
        self._pending_attempt = 0

    def cancel_pending(self):
        """Call when this channel is being torn down (e.g. manual
        disconnect for a physical module swap) while a command may
        still be in flight - without this, an already-running response
        timer keeps ticking on an object nothing else references anymore,
        and fires a misleading "no response" warning later, possibly
        after this same address is already back online under a fresh
        controller."""
        self._cancel_pending_timeout()
        self._close_temp_conn()
        self._queue.clear()

    def _on_response_timeout(self):
        self._pending_attempt += 1
        if self._pending_attempt < RETRY_MAX_ATTEMPTS:
            # No response yet, but that's not necessarily a dead
            # module - on a shared line the failure is probabilistic,
            # so resend the exact same frame and try again rather than
            # giving up after one unlucky attempt.
            frame, label, state_update = self._pending_frame, self._pending_label, self._pending_state_update
            self._pending_timer = None
            if self._temp_conn is not None and self._temp_conn.is_connected():
                self._send(frame, label, state_update)
            else:
                self._open_and_send(frame, label, state_update)
            return

        label = self._pending_label
        state_update = self._pending_state_update
        self._pending_timer = None
        self._pending_label = None
        self._pending_state_update = None
        self._pending_frame = None
        self._pending_attempt = 0
        self._close_temp_conn()

        if state_update:
            # Confirmed on real hardware: an unacknowledged Output ON/OFF
            # often still reaches the module and takes effect even though
            # the return path never gets a readable response back - the
            # collision affects both directions, but not always both at
            # once. Rather than reverting the card back to its last
            # confirmed state (implying nothing happened when it likely
            # did), apply the change anyway and say plainly that it's
            # unconfirmed, not silently pretend it's as good as a real ack.
            msg = (
                f"{self.display_name}: no response after {RETRY_MAX_ATTEMPTS} attempts "
                f"for {label} - applied anyway, UNCONFIRMED (module may not have received it)."
            )
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)
            self.state.update(**state_update)
        else:
            # No state to optimistically apply (e.g. a plain status
            # query) - nothing to do but report the failure and resync
            # the UI to whatever the real last-confirmed values are.
            msg = f"{self.display_name}: no response after {RETRY_MAX_ATTEMPTS} attempts for: {label}"
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)
            self.state.update()
        self._send_next()

    def handle_frame(self, frame: ParsedFrame):
        """Called for any frame addressed to us - either from our own
        temporary connection's response, or (during initial discovery
        seeding) passed in directly before this controller manages its
        own connections."""
        pending_update = self._pending_state_update
        pending_label = self._pending_label
        self._cancel_pending_timeout()
        self._close_temp_conn()
        if self.logger:
            self.logger.info(f"RX ch{self.address}: {frame.raw.hex(' ').upper()} -> {frame.describe()}")

        if frame.type in (c.TYPE_OUTPUT_SWITCH, c.TYPE_SIGNAL_CONTROL) and len(frame.buf) == 1:
            if frame.buf[0] == c.RESP_SUCCESS:
                if pending_update:
                    self.state.update(**pending_update)
            else:
                # Explicit rejection (RESP_FAILED) - same reasoning as the
                # timeout path: state.data was never touched, so this just
                # needs to force a resync rather than apply anything.
                msg = f"{self.display_name}: device rejected {pending_label or 'command'}"
                if self.logger:
                    self.logger.warning(msg)
                self.command_timeout.emit(msg)
                self.state.update()
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
                power_code=pw_code,
            )
            self._send_next()
