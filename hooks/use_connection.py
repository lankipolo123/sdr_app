import time

from PySide6.QtCore import QObject, Signal

from services.serial import SerialManager, SerialThread, list_com_ports

CONNECT_RETRY_ATTEMPTS = 3
CONNECT_RETRY_DELAY_S = 0.3


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

    def connect(self, port_name: str, baud: int = 115200, parity: str = "N", data_bits: int = 8,
                retry: bool = True) -> bool:
        # Windows can briefly hold a COM port after a prior close() even
        # though close() has already returned - opening it again right
        # away can fail with "Access is denied" for a moment before the
        # OS actually releases it. Worth a short bounded retry when
        # reopening a port we have real reason to trust (the one this
        # channel was just using, or its preferred_port - see
        # ChannelController._find_and_open_connection). retry=False skips
        # that wait entirely - used when brute-force sweeping many
        # candidate ports we know nothing about yet, where a genuinely
        # wrong/absent port fails immediately anyway and retrying it 3x
        # with a sleep between each attempt just blocks the GUI thread
        # for no benefit, once per wrong port, on every single command.
        last_error = None
        attempts = CONNECT_RETRY_ATTEMPTS if retry else 1
        for attempt in range(attempts):
            try:
                self.manager.open(port_name, baud, parity, data_bits)
                self.thread.start_reading()
                self.connected_changed.emit(True)
                return True
            except Exception as e:
                last_error = e
                if attempt < attempts - 1:
                    time.sleep(CONNECT_RETRY_DELAY_S)
        self.error.emit(f"Failed to open {port_name}: {last_error}")
        return False

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
            # Clear out anything sitting in the receive buffer from
            # before this query - on a shared line, stray idle noise
            # from the other module could otherwise still be queued
            # ahead of the real response.
            self.manager.reset_input_buffer()
            self.manager.write(data)
            self.raw_tx.emit(data)
            return True
        except Exception as e:
            self.error.emit(f"Write failed: {e}")
            return False
