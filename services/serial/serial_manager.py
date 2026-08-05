import serial
import serial.tools.list_ports

BAUD_RATE = 115200

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
        # Only DTR is touched here, not RTS. Setting dtr=False BEFORE
        # open() (not passed to the constructor - pyserial doesn't accept
        # it there) means opening the port can't pulse DTR high on its
        # own - many cheap USB-serial bridges wire DTR straight to the
        # attached board's reset pin (the classic reason an Arduino
        # reboots every time a serial monitor connects to it). RTS is
        # left at pyserial's real default (True) deliberately - a lot of
        # these same cheap RS422/485 USB adapters use RTS itself as the
        # converter's transmit-enable line, so forcing it low would stop
        # the adapter from ever transmitting anything at all, which is a
        # worse failure than the one this is meant to fix.
        self._port = serial.Serial()
        self._port.port = port_name
        self._port.baudrate = baud
        self._port.bytesize = DATA_BITS_MAP.get(data_bits, serial.EIGHTBITS)
        self._port.parity = PARITY_MAP.get(parity, serial.PARITY_NONE)
        self._port.stopbits = serial.STOPBITS_ONE
        self._port.timeout = 0.2
        self._port.dtr = False
        # Idle state is RTS low - see write() for why. Starting low
        # instead of pyserial's real default (True) means the adapter's
        # transmitter (if it's gated by RTS, common on cheap RS422/485
        # USB bridges) doesn't stay asserted on the line except during
        # an actual write.
        self._port.rts = False
        self._port.open()

    def close(self):
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None

    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open

    def write(self, data: bytes):
        if not self.is_open():
            raise RuntimeError("Port not open")
        # Classic manual half-duplex direction control, from the era
        # before adapters did this on their own: assert RTS only for the
        # duration of an actual transmission, drop it immediately after.
        # flush() blocks until the OS has actually finished shifting the
        # bytes out - dropping RTS before that would cut the transmission
        # off mid-byte on any adapter that really does gate its driver
        # this way. Harmless on an adapter that ignores RTS entirely.
        self._port.rts = True
        self._port.write(data)
        self._port.flush()
        self._port.rts = False

    def read(self, size: int = 256) -> bytes:
        if not self.is_open():
            return b""
        return self._port.read(size)
