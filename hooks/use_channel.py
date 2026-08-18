import struct
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from services.middleware import dll_log_text
from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame, describe_command
from state.channel_state import ChannelState
from state.level_map import LEVEL_TO_HEX
from .use_connection import ConnectionController

RESPONSE_TIMEOUT_MS = 300
# Real hardware test logs (both modules wired in) showed the retry
# buying nothing: 28 attempts across 14 commands, every single retry
# failed identically to the attempt before it - not the probabilistic
# "some get through, some don't" pattern retrying is meant to help
# with. A single attempt gets the same real-world result with half
# the wire traffic and half the log noise per command.
RETRY_MAX_ATTEMPTS = 1


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
    busy_changed = Signal(bool)  # True while a command is queued/in-flight - lets the UI show "sending"
    raw_tx = Signal(bytes)  # forwarded from whichever temp ConnectionController is currently in use
    raw_rx = Signal(bytes)

    def __init__(self, state: ChannelState, baud: int = 115200, parity: str = "N",
                 data_bits: int = 8, logger=None, preferred_port: str | None = None,
                 port_scheduler=None):
        super().__init__()
        self.state = state
        self.baud = baud
        self.parity = parity
        self.data_bits = data_bits
        self.logger = logger
        # Which port to try first, before falling back to sweeping every
        # other available port. Starts None (no discovery step to seed
        # it anymore) but self-learns from here on: the first command
        # that finds a working port remembers it (see
        # _find_and_open_connection), so only that first command ever
        # pays the cost of sweeping unknown ports - every command after
        # that goes straight to the known-good one.
        self.preferred_port = preferred_port
        # Shared across every channel (and Query) - only one command
        # anywhere is ever allowed to actively use the port at a time,
        # see hooks/use_port_scheduler.py. Optional only so this class
        # stays constructible without one (e.g. quick standalone use);
        # ChannelManager always provides the real shared instance.
        self.port_scheduler = port_scheduler
        self._awaiting_port = False  # requested the scheduler, callback hasn't fired yet
        self._temp_conn: ConnectionController | None = None
        self._pending_timer: QTimer | None = None
        self._pending_label = None
        self._pending_state_update: dict | None = None
        self._pending_frame: bytes | None = None
        self._pending_attempt = 0
        self._queue: deque = deque()  # commands waiting for the in-flight one to finish
        self._busy = False

    # ---- Identity ----

    @property
    def address(self) -> int:
        return self.state.data.address

    @property
    def wire_address(self) -> int:
        # The byte that actually goes out on the wire (and that a real
        # module echoes back in its response) is 1-16, matching CH01-16
        # exactly - not the internal 0-based address used everywhere
        # else (loop indices, dict keys, config storage). Every frame
        # this controller sends/checks must use this, never the raw
        # address, or CH02 would talk to whatever's actually configured
        # as address 1 while showing itself as "2".
        return self.state.display_number

    @property
    def display_name(self) -> str:
        # Matches ChannelCard's own title exactly (f"CH{display_number:02d}")
        # - any message shown to the user has to use this, never the raw
        # protocol address, or it won't match the card it's about.
        return f"CH{self.state.display_number:02d}"

    # ---- Public commands ----

    def turn_output_on(self):
        self._enqueue(commands.output_on(self.wire_address), "Output ON", {"output_on": True})

    def turn_output_off(self):
        self._enqueue(commands.output_off(self.wire_address), "Output OFF", {"output_on": False})

    def set_power(self, power_code: int):
        """Resend Signal Control with this channel's own stored Mode/
        Frequency/Bandwidth unchanged, plus the new Power value - the only
        field the customer can actually change. A REAL baseline for those
        three fields only ever comes from a confirmed Status Query
        response (read_status()), which nothing calls automatically
        anymore now that there's no discovery step - so in practice this
        almost always falls back to BLIND_DEFAULT_MODE/FREQ_MHZ/
        BANDWIDTH_MHZ instead of refusing. Explicitly accepted as a real
        risk (this can send an incorrect frequency/bandwidth to a module
        whose actual configuration was never confirmed) so Power can
        still be blind-sent to any address, same as Output ON/OFF
        already could."""
        d = self.state.data
        blind = d.mode is None or d.frequency_mhz is None or d.bandwidth_mhz is None
        mode = d.mode if d.mode is not None else c.BLIND_DEFAULT_MODE
        freq = d.frequency_mhz if d.frequency_mhz is not None else c.BLIND_DEFAULT_FREQ_MHZ
        bandwidth = d.bandwidth_mhz if d.bandwidth_mhz is not None else c.BLIND_DEFAULT_BANDWIDTH_MHZ

        if blind:
            msg = (
                f"{self.display_name}: no status baseline yet - sending power_code=0x{power_code:02X} "
                f"with GUESSED mode/frequency/bandwidth defaults (blind, unconfirmed)."
            )
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)

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
        frame = commands.set_signal(self.wire_address, mode, freq, bandwidth, power_code)
        label = f"Power -> 0x{power_code:02X}" + (" (blind, guessed mode/freq/bw)" if blind else "")
        self._enqueue(frame, label, {"power_code": power_code})

    def set_mode(self, mode: int):
        """Mirror image of set_power(): resend Signal Control with this
        channel's own stored Frequency/Bandwidth/Power unchanged, plus the
        new Mode. Same blind-guess fallback and same accepted risk - and
        same reasoning as set_power() for not touching output_on: Signal
        Control alone never re-enables RF output, so changing mode while
        output is off is harmless, it just won't turn anything on.

        Power falls back to the level the slider is currently set to
        resume from (LEVEL_TO_HEX[last_level]) rather than a fixed guess -
        last_level is never 0/off (see state/level_map.py), so this is
        always a real level the customer has actually chosen, closer to
        their intent than an arbitrary default would be."""
        d = self.state.data
        blind = d.frequency_mhz is None or d.bandwidth_mhz is None or d.power_code is None
        freq = d.frequency_mhz if d.frequency_mhz is not None else c.BLIND_DEFAULT_FREQ_MHZ
        bandwidth = d.bandwidth_mhz if d.bandwidth_mhz is not None else c.BLIND_DEFAULT_BANDWIDTH_MHZ
        power_code = d.power_code if d.power_code is not None else LEVEL_TO_HEX[d.last_level]

        if blind:
            msg = (
                f"{self.display_name}: no status baseline yet - sending mode={c.MODE_NAMES[mode]} "
                f"with GUESSED frequency/bandwidth/power defaults (blind, unconfirmed)."
            )
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)

        frame = commands.set_signal(self.wire_address, mode, freq, bandwidth, power_code)
        label = f"Mode -> {c.MODE_NAMES[mode]}" + (" (blind, guessed freq/bw/power)" if blind else "")
        self._enqueue(frame, label, {"mode": mode})

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
        self._enqueue(commands.query_status(self.wire_address), "Status query")

    # ---- Queueing ----

    def _enqueue(self, frame: bytes, label: str, state_update: dict | None = None):
        self._queue.append((frame, label, state_update))
        if self._pending_timer is None and self._temp_conn is None and not self._awaiting_port:
            self._send_next()

    def _set_busy(self, value: bool):
        if self._busy == value:
            return
        self._busy = value
        self.busy_changed.emit(value)

    def _send_next(self):
        if not self._queue:
            # Nothing left for us to do - release whatever slot we
            # might still be holding (a no-op if we aren't) so the
            # next thing in line, if anything, can get its turn.
            if self.port_scheduler is not None:
                self.port_scheduler.release(self)
            self._set_busy(False)
            return
        frame, label, state_update = self._queue.popleft()
        self._pending_attempt = 0
        self._pending_frame, self._pending_label, self._pending_state_update = frame, label, state_update
        self._set_busy(True)
        self._request_attempt()  # releases our own held slot (if any) and re-acquires for this attempt

    # ---- Port acquisition ----

    def _request_attempt(self):
        # Asks for the port for exactly ONE attempt at the currently
        # pending command - not for the whole command's retry cycle.
        # Called again for every retry (see _on_response_timeout), so a
        # channel stuck retrying a dead address only ever holds the
        # port for one attempt at a time before giving someone else
        # (another channel, Query) a turn, instead of hogging it for
        # the full ~5-6s worst case.
        if self.port_scheduler is None:
            self._open_and_send(self._pending_frame, self._pending_label, self._pending_state_update)
            return
        # Release our own held slot first (a no-op if we aren't holding
        # it, e.g. the very first attempt) - otherwise a retry would
        # re-acquire while still marked as the current holder and just
        # queue behind itself, since the scheduler only grants
        # immediately when nobody holds it.
        self.port_scheduler.release(self)
        self._awaiting_port = True
        self.port_scheduler.acquire(self, self._on_port_granted)

    def _on_port_granted(self):
        self._awaiting_port = False
        self._open_and_send(self._pending_frame, self._pending_label, self._pending_state_update)

    # ---- Send + receive ----

    def _open_and_send(self, frame: bytes, label: str, state_update: dict | None):
        # Brute-force find a port fresh for this command - try every
        # currently available port until one opens, same "just find one
        # that works" spirit as the reference tool's button-press
        # behavior. Opened fresh for every individual attempt (including
        # retries - see _on_response_timeout) and closed right after,
        # so the port scheduler slot is only ever held for one attempt
        # at a time, not the whole command's retry cycle.
        conn = self._find_and_open_connection()
        if conn is None:
            if self.logger:
                self.logger.warning(f"TX ch{self.wire_address} ({label}): no port opened successfully.")
            self._pending_frame = frame
            self._pending_label = label
            self._pending_state_update = state_update
            self._on_response_timeout()  # feeds the same retry/give-up logic as an unanswered send
            return

        self._temp_conn = conn
        conn.frame_received.connect(self._on_frame_received)
        conn.raw_tx.connect(self.raw_tx.emit)
        conn.raw_rx.connect(self.raw_rx.emit)
        conn.raw_rx.connect(self._on_raw_rx_bytes)
        self._send(frame, label, state_update)

    def _on_raw_rx_bytes(self, chunk: bytes):
        # Fires for ANY bytes actually read off the port, even ones that
        # never form a complete/valid frame (see SerialThread.run - this
        # is emitted before the frame parser even runs). Only a fully
        # parsed, matching frame gets logged to the file today (see
        # handle_frame) - on a collision-prone line that leaves a real
        # gap: "zero RX log lines" could mean either genuinely nothing
        # arrived, or something arrived and never resolved into a valid
        # frame, and those mean very different things when diagnosing a
        # dead receive path. Logging every raw chunk closes that gap.
        if self.logger:
            # No raw hex in the log, same rule as the GUI - see
            # services/middleware.py's dll_log_text().
            self.logger.info(f"RAW RX ch{self.wire_address}: {dll_log_text(chunk)}")

    def _find_and_open_connection(self) -> ConnectionController | None:
        ports = ConnectionController.list_ports()
        if self.preferred_port in ports:
            ports = [self.preferred_port] + [p for p in ports if p != self.preferred_port]
        for port in ports:
            conn = ConnectionController()
            if conn.connect(port, self.baud, self.parity, self.data_bits):
                self.preferred_port = port
                return conn
        return None

    def _send(self, frame: bytes, label: str, state_update: dict | None = None):
        # Deliberately does NOT call state.update() here - only a confirmed
        # response (handle_frame) should trigger the state's `changed`
        # signal, or the UI would resync from stale hardware state and
        # visibly snap the slider back before the real ack arrives.
        if self.logger:
            attempt_note = f" (attempt {self._pending_attempt + 1}/{RETRY_MAX_ATTEMPTS})" if self._pending_attempt else ""
            # describe_command decodes the actual frame bytes (mode/freq/
            # bw/power spelled out, power as Low/Med/High/Off) - label is
            # kept too since it says what the USER'S action was (e.g. "Power
            # -> Low"), which the full decoded frame alone doesn't capture
            # (Signal Control always resends all 4 fields together, so the
            # decode can't tell which one the user actually meant to change).
            self.logger.info(
                f"TX ch{self.wire_address} ({label}){attempt_note}: "
                f"{describe_command(frame)} | {dll_log_text(frame)}"
            )

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
            # ConnectionController defines its own disconnect() (closes
            # the port) which shadows QObject's signal-disconnecting one
            # - it doesn't touch these connections at all, so each has to
            # be torn down explicitly or the temp connection being
            # garbage-collected is the only thing that would eventually
            # clean them up.
            for signal, slot in (
                (self._temp_conn.frame_received, self._on_frame_received),
                (self._temp_conn.raw_tx, self.raw_tx.emit),
                (self._temp_conn.raw_rx, self.raw_rx.emit),
                (self._temp_conn.raw_rx, self._on_raw_rx_bytes),
            ):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            self._temp_conn.disconnect()
            self._temp_conn = None

    def _on_frame_received(self, frame: ParsedFrame):
        if frame.addr != self.wire_address:
            return  # not addressed to us - stray traffic, ignore
        self.handle_frame(frame)

    # ---- Timeout + retry ----

    def _reset_pending(self) -> tuple[str | None, dict | None]:
        """Clears all _pending_* bookkeeping for whatever command was in
        flight, returning (label, state_update) as they were just
        before clearing - callers that need to report/apply based on
        the old value use the return, callers that don't (e.g. tearing
        down) just ignore it. Safe to call whether the timer is still
        running or already fired - QTimer.stop() on an already-fired
        singleShot timer is a documented no-op."""
        label = self._pending_label
        state_update = self._pending_state_update
        if self._pending_timer is not None:
            self._pending_timer.stop()
            self._pending_timer = None
        self._pending_label = None
        self._pending_state_update = None
        self._pending_frame = None
        self._pending_attempt = 0
        return label, state_update

    def _cancel_pending_timeout(self):
        self._reset_pending()

    def cancel_pending(self):
        """Call when this channel is being torn down (e.g. manual
        disconnect for a physical module swap) while a command may
        still be in flight - without this, an already-running response
        timer keeps ticking on an object nothing else references anymore,
        and fires a misleading "no response" warning later, possibly
        after this same address is already back online under a fresh
        controller. Also releases/cancels the shared port scheduler slot
        if held or queued - otherwise a channel torn down mid-turn would
        leave every other channel waiting for a turn that never comes."""
        self._cancel_pending_timeout()
        self._close_temp_conn()
        self._queue.clear()
        self._awaiting_port = False
        if self.port_scheduler is not None:
            self.port_scheduler.cancel(self)
        self._set_busy(False)

    def _on_response_timeout(self):
        self._pending_attempt += 1
        if self._pending_attempt < RETRY_MAX_ATTEMPTS:
            # No response yet, but that's not necessarily a dead
            # module - on a shared line the failure is probabilistic,
            # so resend the exact same frame and try again rather than
            # giving up after one unlucky attempt. Releases the port
            # scheduler and re-acquires it for this next attempt (via
            # _request_attempt) instead of just reusing the held
            # connection - otherwise this one channel would keep the
            # port to itself for every retry in a row, starving every
            # other channel and Query for the whole cycle instead of
            # just this one attempt.
            self._pending_timer = None
            self._close_temp_conn()
            self._request_attempt()
            return

        label, state_update = self._reset_pending()
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
        """Called for any frame addressed to us, from our own temporary
        connection's response. Only actually acts on a frame that
        matches what's currently pending - the protocol has no checksum
        (confirmed earlier: noise can parse as a structurally valid but
        semantically bogus frame), so on a collision-prone line, a
        Status-Query-shaped frame can occasionally arrive while this
        channel only ever asked for a plain Output ON/OFF ack (nothing
        in the app calls read_status() right now - every Status Query
        branch hit is either a real, deliberately requested one, or
        noise). Blindly trusting anything that merely looks like a
        valid frame used to stomp the card's real output/power state
        with effectively random bytes. Anything unexpected is ignored
        and left for the already-running response timer to handle
        (retry, or give up and apply optimistically) - same as if
        nothing had arrived at all."""
        pending_label = self._pending_label
        is_ack = frame.type in (c.TYPE_OUTPUT_SWITCH, c.TYPE_SIGNAL_CONTROL) and len(frame.buf) == 1
        is_status = frame.type == c.TYPE_STATUS_QUERY and len(frame.buf) >= 6

        if is_status and pending_label != "Status query":
            if self.logger:
                self.logger.warning(
                    f"{self.display_name}: ignoring unexpected Status Query frame "
                    f"while waiting for {pending_label or 'nothing'} - likely "
                    f"collision noise, not a real response: {dll_log_text(frame.raw)}"
                )
            return
        if not is_ack and not is_status:
            if self.logger:
                self.logger.warning(
                    f"{self.display_name}: ignoring unrecognized frame while "
                    f"waiting for {pending_label or 'nothing'}: {dll_log_text(frame.raw)}"
                )
            return

        pending_update = self._pending_state_update
        self._cancel_pending_timeout()
        self._close_temp_conn()
        if self.logger:
            self.logger.info(f"RX ch{self.wire_address}: {dll_log_text(frame.raw)} -> {frame.describe()}")

        if is_ack:
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
        else:  # is_status
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
