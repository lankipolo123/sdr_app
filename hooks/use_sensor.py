from utils.signal import Signal, SingleShotTimer
from services.modbus import build_read_input_registers, parse_read_input_registers_response, ModbusError

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

SENSOR_SLAVE_ADDR = 1
# Confirmed against real hardware in the C rewrite (see its
# PLAN_temp_sensor.md / sensor.h): QModMaster's "Base Addr: 1" status
# line turned out to mean its "Start Address" field is 1-based over a
# 0-based wire address - register 1 on the wire, not 2.
SENSOR_START_REGISTER = 1
SENSOR_REGISTER_COUNT = 2
SENSOR_BAUD = 9600
SENSOR_PARITY = "N"
SENSOR_DATA_BITS = 8
SENSOR_POLL_INTERVAL_MS = 3000
SENSOR_READ_TIMEOUT_S = 0.5
# addr + func + byte_count + 2 registers*2 bytes + crc16
_EXPECTED_RESPONSE_LEN = 3 + SENSOR_REGISTER_COUNT * 2 + 2

_PARITY_MAP = {"N": "N", "E": "E", "O": "O"}


def _initial_state() -> dict:
    return {
        "connected": False,
        "online": False,
        "has_reading": False,
        "temperature_c": 0.0,
        "humidity_pct": 0.0,
        "attempt_count": 0,
        "last_rx_len": 0,
    }


class SensorController:
    """XY-MD02 temperature/humidity sensor over Modbus RTU, on its own
    serial port completely independent of the RS-422/Transit.dll bus the
    channel cards use.

    Unlike the channel cards' blind sends (fire once, apply
    optimistically), a register read genuinely needs the reply - there's
    no value to show without it - so this waits for a real response.
    Each poll cycle runs on its own background thread (SingleShotTimer,
    same as everywhere else in this app) but pyserial's bounded
    `timeout=` makes a plain blocking write+read safe there: unlike the
    C rewrite's WinAPI immediate-return non-blocking reads (needed
    because its single thread also owns the message loop), this app's
    poll threads own nothing else, so there's no state machine to hand-
    roll here.
    """

    def __init__(self, logger=None):
        self.changed = Signal()
        self.logger = logger
        self._serial = None
        self._timer = SingleShotTimer()
        self._timer.timeout.connect(self._poll)
        self.state = _initial_state()

    @staticmethod
    def list_ports() -> list[str]:
        if serial is None:
            return []
        return [p.device for p in serial.tools.list_ports.comports()]

    def is_connected(self) -> bool:
        return self._serial is not None

    def get_state(self) -> dict:
        return dict(self.state)

    def connect(self, port_name: str) -> bool:
        if serial is None:
            if self.logger:
                self.logger.warning("Sensor: pyserial isn't installed - run 'pip install pyserial'")
            return False
        if self.is_connected():
            return True
        try:
            ser = serial.Serial(
                port_name,
                baudrate=SENSOR_BAUD,
                bytesize=SENSOR_DATA_BITS,
                parity=_PARITY_MAP.get(SENSOR_PARITY, "N"),
                stopbits=serial.STOPBITS_ONE,
                timeout=SENSOR_READ_TIMEOUT_S,
                write_timeout=SENSOR_READ_TIMEOUT_S,
            )
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Sensor: failed to open {port_name}: {e}")
            return False

        # Same fix as the C rewrite's serial_open(): explicitly disable
        # RTS rather than leaving it at the driver's inherited/undefined
        # state. An RS-485 USB adapter often uses RTS as its transmit/
        # receive direction switch - an inherited "stuck asserted" RTS
        # can latch it in transmit-only mode, so requests go out fine but
        # it never listens for a reply (indistinguishable from a dead
        # sensor without this).
        try:
            ser.rts = False
            ser.dtr = True
        except Exception:
            pass

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        self._serial = ser
        self.state = _initial_state()
        self.state["connected"] = True
        self._notify()
        self._timer.start(0)
        return True

    def disconnect(self) -> None:
        self._timer.stop()
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        # Reset to unknown rather than leaving a stale reading on screen -
        # same "never show a value we can't currently vouch for" rule the
        # rest of this app family follows.
        self.state = _initial_state()
        self._notify()

    def _notify(self) -> None:
        self.changed.emit(self.get_state())

    def _poll(self) -> None:
        if not self.is_connected():
            return

        request = build_read_input_registers(SENSOR_SLAVE_ADDR, SENSOR_START_REGISTER, SENSOR_REGISTER_COUNT)
        self.state["attempt_count"] += 1

        try:
            self._serial.reset_input_buffer()
            self._serial.write(request)
        except Exception as e:
            self._port_lost(str(e))
            return

        try:
            response = self._serial.read(_EXPECTED_RESPONSE_LEN)
        except Exception as e:
            self._port_lost(str(e))
            return

        self.state["last_rx_len"] = len(response)

        try:
            registers = parse_read_input_registers_response(response, SENSOR_SLAVE_ADDR, SENSOR_REGISTER_COUNT)
            self.state["temperature_c"] = registers[0] / 10.0
            self.state["humidity_pct"] = registers[1] / 10.0
            self.state["has_reading"] = True
            self.state["online"] = True
        except ModbusError:
            # No reply, a corrupted reply, or a device-side exception this
            # cycle - normal, stays connected, tries again next interval.
            self.state["online"] = False

        self._notify()
        self._timer.start(SENSOR_POLL_INTERVAL_MS)

    def _port_lost(self, error: str) -> None:
        # A hard write/read failure (as opposed to "no bytes back", which
        # pyserial reports as success with an empty result) means the
        # port itself is gone - most likely the USB adapter was unplugged.
        # Disconnect immediately so is_connected()/the UI reflect that,
        # rather than staying "connected" against a dead handle forever -
        # the same fix just shipped for the RS-422 and sensor ports in
        # the C rewrite (digital-noise-configuration-multi).
        if self.logger:
            self.logger.warning(f"Sensor: port error, disconnecting - {error}")
        self.disconnect()
