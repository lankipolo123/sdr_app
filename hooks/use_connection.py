from PySide6.QtCore import QObject, Signal

from services.serial import SerialManager, SerialThread, list_com_ports


class ConnectionController(QObject):
    connected_changed = Signal(bool)
    frame_received = Signal(object)
    raw_rx = Signal(bytes)
    raw_tx = Signal(bytes)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.manager = SerialManager()
        self.thread = SerialThread(self.manager)
        self.thread.frame_received.connect(self.frame_received.emit)
        self.thread.raw_rx.connect(self.raw_rx.emit)
        self.thread.error.connect(self.error.emit)

    @staticmethod
    def list_ports():
        return list_com_ports()

    def connect(self, port_name: str, baud: int = 115200, parity: str = "N", data_bits: int = 8) -> bool:
        try:
            self.manager.open(port_name, baud, parity, data_bits)
        except Exception as e:
            self.error.emit(f"Failed to open {port_name}: {e}")
            return False
        self.thread.start_reading()
        self.connected_changed.emit(True)
        return True

    def disconnect(self):
        # stop_reading() waits for the thread to actually finish before
        # this closes the port - see SerialThread.stop_reading() for why
        # that order matters (closing first while the thread could still
        # be mid-read is a real race that can break reopening the port).
        self.thread.stop_reading()
        self.manager.close()
        self.connected_changed.emit(False)

    def is_connected(self) -> bool:
        return self.manager.is_open()

    def send(self, data: bytes) -> bool:
        if not self.is_connected():
            self.error.emit("Cannot send: not connected")
            return False
        try:
            self.manager.write(data)
            self.raw_tx.emit(data)
            return True
        except Exception as e:
            self.error.emit(f"Write failed: {e}")
            return False
