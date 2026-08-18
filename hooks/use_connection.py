from PySide6.QtCore import QObject, Signal

from services.middleware import dll_auto_connect, dll_check_connection, dll_disconnect, dll_send_command


class ConnectionController(QObject):

    connected_changed = Signal(bool)
    frame_received = Signal(object)
    raw_rx = Signal(bytes)
    raw_tx = Signal(bytes)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._connected = False

    @staticmethod
    def list_ports():
        return ["DLL"]

    def connect(self, port_name: str = "DLL", baud: int = 115200, parity: str = "N", data_bits: int = 8) -> bool:
        return_code, buffer_text, error = dll_auto_connect()
        if return_code is None:
            self.error.emit(f"AutoConnectSDR unreachable: {error}")
            return False
        self._connected = buffer_text == "Connected"
        self.connected_changed.emit(self._connected)
        if not self._connected:
            self.error.emit(f"AutoConnectSDR: not connected (return={return_code}, buffer={buffer_text!r})")
        return self._connected

    def disconnect(self):
        dll_disconnect()
        self._connected = False
        self.connected_changed.emit(False)

    def is_connected(self) -> bool:
        return self._connected

    def check_connection(self):
        return dll_check_connection()

    def send(self, data: bytes) -> bool:
        if not self.is_connected():
            self.error.emit("Cannot send: not connected")
            return False
        return_code, error = dll_send_command(data)
        if return_code is None:
            self.error.emit(f"SendCommandToSDR unreachable: {error}")
            return False
        self.raw_tx.emit(data)
        if return_code < 0:
            self.error.emit(f"SendCommandToSDR returned {return_code} (meaning not confirmed yet)")
        return True
