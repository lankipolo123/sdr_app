import time

from PySide6.QtCore import QObject, QTimer, Signal

from services import modbus

try:
    import serial
    from serial.tools import list_ports as _list_ports
except ImportError:  # pragma: no cover - pyserial not installed in this env
    serial = None
    _list_ports = None

# XY-MD02 temperature/humidity sensors over Modbus RTU, on their own USB-
# RS485 adapter - a real, separate raw serial connection, completely
# independent of the RS-422/Transit.dll bus the channel cards use (see
# hooks/use_connection.py). Direct port of the C rewrite's src/sensor.c:
# NOT one sensor per RF channel - there are SENSOR_MAX_UNITS physical
# sensor units total, scanning the rack area collectively, independent
# of the 16 RF channels. Each has its own configured Modbus slave
# address (defaults to unit index + 1, i.e. 1-4; real wiring may not be
# sequential). Round-robins continuously - one unit in flight at a time,
# PER_UNIT_GAP_MS between finishing one and starting the next - rather
# than waiting a full poll interval per unit, so a full 4-unit round
# trip stays fast enough to notice an overtemp promptly.
#
# PySide6 has no native async serial I/O the way Node's SerialPort does,
# so this drives a hand-rolled non-blocking state machine off a QTimer
# tick (same shape as the C rewrite's WM_TIMER-driven sensor_poll()),
# rather than the event-driven style hooks/use_sensor.py's Electron
# sibling uses - the port itself is opened with timeout=0 (non-blocking
# reads) for exactly this reason.
SENSOR_MAX_UNITS = 4
SENSOR_BAUD = 9600
TICK_MS = 50
PER_UNIT_GAP_MS = 150
RESPONSE_TIMEOUT_MS = 500


class SensorUnitState:

    def __init__(self, address: int):
        self.address = address
        self.online = False
        self.has_reading = False
        self.temperature_c = 0.0
        self.humidity_pct = 0.0
        self.attempt_count = 0
        self.last_rx_len = 0


class SensorController(QObject):

    changed = Signal()
    port_lost = Signal(str)

    def __init__(self):
        super().__init__()
        self.units = [SensorUnitState(i + 1) for i in range(SENSOR_MAX_UNITS)]
        self.connected = False
        self._port = None
        self._rx_buf = bytearray()
        self._current_unit = 0
        self._waiting = False
        self._next_poll_at = 0.0
        self._response_deadline = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def list_ports() -> list[str]:
        if _list_ports is None:
            return []
        return [p.device for p in _list_ports.comports()]

    def average_temperature(self) -> float | None:
        """Mean temperature across every unit that currently has a real
        reading - units still waiting on their first reply don't skew
        it. Returns None if no unit has a reading yet, same "don't show
        a value we can't vouch for" rule as everything else here."""
        readings = [u.temperature_c for u in self.units if u.has_reading]
        if not readings:
            return None
        return sum(readings) / len(readings)

    def connect(self, port_name: str) -> bool:
        if serial is None:
            return False
        if self.connected:
            return True
        try:
            port = serial.Serial(
                port_name, baudrate=SENSOR_BAUD, bytesize=8, parity="N",
                stopbits=1, timeout=0, write_timeout=1,
            )
            # Same fix as the C rewrite's serial_open(): explicitly set
            # RTS/DTR rather than leaving them at an inherited/undefined
            # state. An RS-485 USB adapter often uses RTS as its
            # transmit/receive direction switch - an inherited "stuck
            # asserted" RTS can latch it in transmit-only mode, so
            # requests go out fine but it never listens for a reply.
            port.rts = False
            port.dtr = True
        except (OSError, serial.SerialException):
            return False

        self._port = port
        self._rx_buf = bytearray()
        self._current_unit = 0
        self.units = [SensorUnitState(i + 1) for i in range(SENSOR_MAX_UNITS)]
        self.connected = True
        self._waiting = False
        self._next_poll_at = time.monotonic()  # poll right away
        self._timer.start(TICK_MS)
        self.changed.emit()
        return True

    def disconnect(self):
        self._timer.stop()
        if self._port is not None:
            try:
                self._port.close()
            except (OSError, serial.SerialException):
                pass
            self._port = None
        self.connected = False
        self._waiting = False
        # Reset to unknown rather than leaving stale readings on screen -
        # same "never show a value we can't currently vouch for" rule
        # the rest of this app family follows.
        self.units = [SensorUnitState(i + 1) for i in range(SENSOR_MAX_UNITS)]
        self.changed.emit()

    def _port_lost(self, error: str):
        # A hard write/read/port error (as opposed to "no bytes back
        # this cycle", which is a normal Modbus timeout, not a port
        # failure) means the port itself is gone - most likely the USB
        # adapter was unplugged.
        self.disconnect()
        self.port_lost.emit(error)

    def _send_request(self):
        unit = self.units[self._current_unit]
        request = modbus.build_read_input_registers(unit.address)
        self._rx_buf = bytearray()
        unit.attempt_count += 1
        try:
            self._port.write(request)
        except (OSError, serial.SerialException) as e:
            self._port_lost(str(e))
            return
        self._waiting = True
        self._response_deadline = time.monotonic() + RESPONSE_TIMEOUT_MS / 1000

    def _finish_cycle(self, got_valid_reply: bool):
        unit = self.units[self._current_unit]
        unit.last_rx_len = len(self._rx_buf)
        unit.online = got_valid_reply
        self._rx_buf = bytearray()
        self._waiting = False
        self._current_unit = (self._current_unit + 1) % SENSOR_MAX_UNITS
        self._next_poll_at = time.monotonic() + PER_UNIT_GAP_MS / 1000
        self.changed.emit()

    def _tick(self):
        if not self.connected:
            return

        if self._waiting:
            unit = self.units[self._current_unit]
            try:
                chunk = self._port.read(64)
            except (OSError, serial.SerialException) as e:
                self._port_lost(str(e))
                return
            if chunk:
                self._rx_buf += chunk

            try:
                registers = modbus.parse_read_input_registers_response(bytes(self._rx_buf), unit.address)
                unit.temperature_c = registers[0] / 10
                unit.humidity_pct = registers[1] / 10
                unit.has_reading = True
                self._finish_cycle(True)
                return
            except modbus.ModbusError:
                if len(self._rx_buf) >= modbus.EXPECTED_RESPONSE_LEN:
                    # Enough bytes came back but they didn't parse (bad
                    # CRC, an exception frame, wrong function/address) -
                    # a real "not responding" outcome this cycle, not
                    # "keep waiting for more bytes".
                    self._finish_cycle(False)
                    return
                # else: still short of EXPECTED_RESPONSE_LEN - keep
                # waiting for either more data or the response timeout.

            if time.monotonic() >= self._response_deadline:
                self._finish_cycle(False)
            return

        # idle
        if time.monotonic() >= self._next_poll_at:
            self._send_request()
