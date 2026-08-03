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
        self._port = serial.Serial(
            port=port_name,
            baudrate=baud,
            bytesize=DATA_BITS_MAP.get(data_bits, serial.EIGHTBITS),
            parity=PARITY_MAP.get(parity, serial.PARITY_NONE),
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
        )

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
