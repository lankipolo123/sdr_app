import struct
from collections import deque

from services.middleware import dll_log_text
from services.protocol import commands, constants as c
from services.protocol.packet_parser import ParsedFrame, describe_command
from state.channel_state import ChannelState
from state.level_map import LEVEL_TO_HEX, HEX_TO_LEVEL, LEVEL_LABELS_FULL
from utils.signal import Signal, SingleShotTimer
from .use_connection import ConnectionController

RESPONSE_TIMEOUT_MS = 300
RETRY_MAX_ATTEMPTS = 1


class ChannelController:

    def __init__(self, state: ChannelState, baud: int = 115200, parity: str = "N",
                 data_bits: int = 8, logger=None, preferred_port: str | None = None,
                 port_scheduler=None):
        self.command_timeout = Signal()
        self.busy_changed = Signal()
        self.raw_tx = Signal()
        self.raw_rx = Signal()
        self.state = state
        self.baud = baud
        self.parity = parity
        self.data_bits = data_bits
        self.logger = logger
        self.preferred_port = preferred_port
        self.port_scheduler = port_scheduler
        self._awaiting_port = False
        self._temp_conn: ConnectionController | None = None
        self._pending_timer: SingleShotTimer | None = None
        self._pending_label = None
        self._pending_state_update: dict | None = None
        self._pending_frame: bytes | None = None
        self._pending_attempt = 0
        self._queue: deque = deque()
        self._busy = False


    @property
    def address(self) -> int:
        return self.state.data.address

    @property
    def wire_address(self) -> int:
        return self.state.display_number

    @property
    def display_name(self) -> str:
        return f"CH{self.state.display_number:02d}"


    def turn_output_on(self):
        self._enqueue(commands.output_on(self.wire_address), "Output ON", {"output_on": True})

    def turn_output_off(self):
        self._enqueue(commands.output_off(self.wire_address), "Output OFF", {"output_on": False})

    def set_power(self, power_code: int):
        d = self.state.data
        blind = d.mode is None or d.frequency_mhz is None or d.bandwidth_mhz is None
        mode = d.mode if d.mode is not None else c.BLIND_DEFAULT_MODE
        freq = d.frequency_mhz if d.frequency_mhz is not None else c.BLIND_DEFAULT_FREQ_MHZ
        bandwidth = d.bandwidth_mhz if d.bandwidth_mhz is not None else c.BLIND_DEFAULT_BANDWIDTH_MHZ

        level_name = LEVEL_LABELS_FULL.get(HEX_TO_LEVEL.get(power_code), "unknown level")

        if blind:
            msg = (
                f"{self.display_name}: no status baseline yet - sending level={level_name} "
                f"with GUESSED mode/frequency/bandwidth defaults (blind, unconfirmed)."
            )
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)

        frame = commands.set_signal(self.wire_address, mode, freq, bandwidth, power_code)
        label = f"Power -> {level_name}" + (" (blind, guessed mode/freq/bw)" if blind else "")
        self._enqueue(frame, label, {"power_code": power_code})

    def set_mode(self, mode: int):
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
        self.turn_output_on()
        self.set_power(power_code)

    def read_status(self):
        self._enqueue(commands.query_status(self.wire_address), "Status query")


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
            if self.port_scheduler is not None:
                self.port_scheduler.release(self)
            self._set_busy(False)
            return
        frame, label, state_update = self._queue.popleft()
        self._pending_attempt = 0
        self._pending_frame, self._pending_label, self._pending_state_update = frame, label, state_update
        self._set_busy(True)
        self._request_attempt()


    def _request_attempt(self):
        if self.port_scheduler is None:
            self._open_and_send(self._pending_frame, self._pending_label, self._pending_state_update)
            return
        self.port_scheduler.release(self)
        self._awaiting_port = True
        self.port_scheduler.acquire(self, self._on_port_granted)

    def _on_port_granted(self):
        self._awaiting_port = False
        self._open_and_send(self._pending_frame, self._pending_label, self._pending_state_update)


    def _open_and_send(self, frame: bytes, label: str, state_update: dict | None):
        conn = self._find_and_open_connection()
        if conn is None:
            if self.logger:
                self.logger.warning(f"TX ch{self.wire_address} ({label}): no port opened successfully.")
            self._pending_frame = frame
            self._pending_label = label
            self._pending_state_update = state_update
            self._on_response_timeout()
            return

        self._temp_conn = conn
        conn.frame_received.connect(self._on_frame_received)
        conn.raw_tx.connect(self.raw_tx.emit)
        conn.raw_rx.connect(self.raw_rx.emit)
        conn.raw_rx.connect(self._on_raw_rx_bytes)
        self._send(frame, label, state_update)

    def _on_raw_rx_bytes(self, chunk: bytes):
        if self.logger:
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
        if self.logger:
            attempt_note = f" (attempt {self._pending_attempt + 1}/{RETRY_MAX_ATTEMPTS})" if self._pending_attempt else ""
            self.logger.info(
                f"TX ch{self.wire_address} ({label}){attempt_note}: "
                f"{describe_command(frame)} | {dll_log_text(frame)}"
            )

        sent = self._temp_conn.send(frame)
        if not sent:
            self._close_temp_conn()
            self._send_next()
            return

        self._pending_frame = frame
        self._pending_label = label
        self._pending_state_update = state_update
        self._pending_timer = SingleShotTimer()
        self._pending_timer.timeout.connect(self._on_response_timeout)
        self._pending_timer.start(RESPONSE_TIMEOUT_MS)

    def _close_temp_conn(self):
        if self._temp_conn is not None:
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
            return
        self.handle_frame(frame)


    def _reset_pending(self) -> tuple[str | None, dict | None]:
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
            self._pending_timer = None
            self._close_temp_conn()
            self._request_attempt()
            return

        label, state_update = self._reset_pending()
        self._close_temp_conn()

        if state_update:
            msg = (
                f"{self.display_name}: no response after {RETRY_MAX_ATTEMPTS} attempts "
                f"for {label} - applied anyway, UNCONFIRMED (module may not have received it)."
            )
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)
            self.state.update(**state_update)
        else:
            msg = f"{self.display_name}: no response after {RETRY_MAX_ATTEMPTS} attempts for: {label}"
            if self.logger:
                self.logger.warning(msg)
            self.command_timeout.emit(msg)
            self.state.update()
        self._send_next()

    def handle_frame(self, frame: ParsedFrame):
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
                msg = f"{self.display_name}: device rejected {pending_label or 'command'}"
                if self.logger:
                    self.logger.warning(msg)
                self.command_timeout.emit(msg)
                self.state.update()
            self._send_next()
        else:
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
