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
        # Configuring dtr/rts False BEFORE open() (not passed to the
        # constructor - pyserial doesn't accept them there) sets the
        # initial line state so opening the port doesn't pulse DTR high
        # on its own. Many cheap USB-serial bridges wire DTR straight to
        # the attached board's reset pin (the classic reason an Arduino
        # reboots every time a serial monitor connects to it) - if this
        # module's board does the same, every connection attempt could
        # be resetting its controller right as the first query goes out,
        # which looks identical to "nothing is there" no matter what
        # address or baud is used.
        self._port = serial.Serial()
        self._port.port = port_name
        self._port.baudrate = baud
        self._port.bytesize = DATA_BITS_MAP.get(data_bits, serial.EIGHTBITS)
        self._port.parity = PARITY_MAP.get(parity, serial.PARITY_NONE)
        self._port.stopbits = serial.STOPBITS_ONE
        self._port.timeout = 0.2
        self._port.dsrdtr = False
        self._port.rtscts = False
        self._port.dtr = False
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
        self._port.write(data)

    def read(self, size: int = 256) -> bytes:
        if not self.is_open():
            return b""
        return self._port.read(size)
