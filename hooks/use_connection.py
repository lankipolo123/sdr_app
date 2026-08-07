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

    def connect(self, port_name: str, baud: int = 115200, parity: str = "N", data_bits: int = 8) -> bool:
        # Windows can briefly hold a COM port after a prior close() even
        # though close() has already returned - opening it again right
        # away can fail with "Access is denied" for a moment before the
        # OS actually releases it. This app opens/closes ports often
        # (every blind-sent command opens its own connection fresh), so
        # a short bounded retry here is worth it rather than treating
        # that transient race as a hard "nothing's there."
        last_error = None
        for attempt in range(CONNECT_RETRY_ATTEMPTS):
            try:
                self.manager.open(port_name, baud, parity, data_bits)
                # Flush whatever's already sitting in the OS receive
                # buffer BEFORE the background read thread starts
                # consuming it - every command opens its own fresh
                # connection on a port other commands were just using, so
                # a late-arriving response to a PREVIOUS command (or
                # stray collision noise) could otherwise get read and
                # handed to this new command as if it were the response
                # to THIS one. send()'s own reset_input_buffer() call
                # happens too late to catch this - by the time it runs,
                # the read thread has already been running for a moment.
                self.manager.reset_input_buffer()
                self.thread.start_reading()
                self.connected_changed.emit(True)
                return True
            except Exception as e:
                last_error = e
                if attempt < CONNECT_RETRY_ATTEMPTS - 1:
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
