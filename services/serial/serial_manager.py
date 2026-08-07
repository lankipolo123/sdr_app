import logging
import time

import serial
import serial.tools.list_ports

# Same named logger the rest of the app uses (setup_logger in
# utils/logging_service.py) - logging.getLogger() with the same name
# always returns the same singleton, so this works without threading a
# logger reference through SerialManager's constructor.
_logger = logging.getLogger("sdr_controller")

BAUD_RATE = 115200

# Gap between asserting RTS and actually writing - some half-duplex
# adapters need their driver stage a moment to actually enable after
# RTS goes high; writing in the same instant can clip the very start of
# the transmission on hardware that needs this. Untried until now;
# harmless on an adapter that doesn't need it.
RTS_TURNAROUND_S = 0.005

# Minimum gap enforced between ANY two writes, regardless of which
# SerialManager instance or port sent them - module-level (not per-
# instance) because two different channels' commands (e.g. address 1
# then address 2) can come from two entirely separate SerialManager
# objects that still end up on the same physical shared adapter. Gives
# the line a moment to settle between transmissions instead of firing
# back-to-back with zero gap.
MIN_SEND_GAP_S = 0.2
_last_write_time = 0.0

# Tried making this wait "responsive" with QCoreApplication.processEvents()
# in short slices (same technique SerialThread.stop_reading() uses) so
# the UI wouldn't freeze during the gap - but write() runs synchronously
# inside a button click's own call stack (ChannelController's send state
# machine isn't written to tolerate being re-entered mid-update), and
# reentering the event loop from there broke cards sending at all while
# Query (a separate, simpler closure) kept working. Reverted to a plain
# blocking sleep - a real UI freeze during the gap, but correct, and the
# freeze is bounded to MIN_SEND_GAP_S per write.

PARITY_MAP = {
    "N": serial.PARITY_NONE,
    "O": serial.PARITY_ODD,
    "E": serial.PARITY_EVEN,
    "M": serial.PARITY_MARK,
    "S": serial.PARITY_SPACE,
}

DATA_BITS_MAP = {
    5: serial.FIVEBITS,
    6: serial.SIXBITS,
    7: serial.SEVENBITS,
    8: serial.EIGHTBITS,
}


def list_com_ports():
    return [p.device for p in serial.tools.list_ports.comports()]


class SerialManager:
    def __init__(self):
        self._port: serial.Serial | None = None

    def open(self, port_name: str, baud: int = BAUD_RATE, parity: str = "N", data_bits: int = 8):
        # dtr=False before open() (not passed to the constructor -
        # pyserial doesn't accept it there) means opening the port can't
        # pulse DTR high on its own - many cheap USB-serial bridges wire
        # DTR straight to the attached board's reset pin. rts=False is
        # the idle state for the manual half-duplex toggle in write()
        # below - only asserted for the duration of an actual
        # transmission, not held constantly.
        self._port = serial.Serial()
        self._port.port = port_name
        self._port.baudrate = baud
        self._port.bytesize = DATA_BITS_MAP.get(data_bits, serial.EIGHTBITS)
        self._port.parity = PARITY_MAP.get(parity, serial.PARITY_NONE)
        self._port.stopbits = serial.STOPBITS_ONE
        self._port.timeout = 0.2
        self._port.dtr = False
        self._port.rts = False
        self._port.open()
        _logger.info(
            f"SerialManager: opened {port_name} at {baud} baud, "
            f"parity={parity}, data_bits={data_bits}, dtr=False, rts=False (idle)"
        )

    def close(self):
        if self._port and self._port.is_open:
            _logger.info(f"SerialManager: closing {self._port.port}")
            self._port.close()
        self._port = None

    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open

    def write(self, data: bytes):
        if not self.is_open():
            raise RuntimeError("Port not open")

        global _last_write_time
        elapsed = time.monotonic() - _last_write_time
        if elapsed < MIN_SEND_GAP_S:
            time.sleep(MIN_SEND_GAP_S - elapsed)

        # Classic manual half-duplex direction control, from the era
        # before adapters did this on their own: assert RTS only for the
        # duration of an actual transmission, drop it immediately after.
        # flush() blocks until the OS has actually finished shifting the
        # bytes out - dropping RTS before that would cut the transmission
        # off mid-byte on any adapter that really does gate its driver
        # this way. Harmless on an adapter that ignores RTS entirely.
        port_name = self._port.port
        _logger.info(f"SerialManager: RTS HIGH on {port_name}, writing {len(data)} bytes: {data.hex(' ').upper()}")
        self._port.rts = True
        time.sleep(RTS_TURNAROUND_S)
        self._port.write(data)
        self._port.flush()
        self._port.rts = False
        _last_write_time = time.monotonic()
        _logger.info(f"SerialManager: RTS LOW on {port_name}, write complete")

    def read(self, size: int = 256) -> bytes:
        if not self.is_open():
            return b""
        return self._port.read(size)

    def reset_input_buffer(self):
        # Discards whatever's sitting in the OS-level receive buffer
        # before a new query goes out - on a shared line, stray idle
        # noise from the other module could otherwise still be queued up
        # ahead of the real response, making a clean answer look
        # corrupted when it wasn't. Safe to call while SerialThread's
        # background read loop is mid-read on another thread - worst
        # case is that one read cycle comes back empty.
        if self.is_open():
            self._port.reset_input_buffer()
