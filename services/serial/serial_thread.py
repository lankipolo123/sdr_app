from PySide6.QtCore import QThread, Signal

from services.protocol.packet_parser import FrameParser
from .serial_manager import SerialManager


class SerialThread(QThread):
    frame_received = Signal(object)
    raw_rx = Signal(bytes)
    error = Signal(str)

    def __init__(self, manager: SerialManager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._parser = FrameParser()
        self._running = False

    def start_reading(self):
        self._running = True
        self.start()

    def stop_reading(self):
        # Only flips the flag - does NOT wait here. The loop below only
        # notices this between read() calls, and a real serial read can
        # block for its full configured timeout (or longer, if the port
        # is in a bad state) before it does. Waiting synchronously right
        # here, before the port gets closed, meant every disconnect
        # click blocked the whole UI for however long that read took -
        # felt like the button just didn't work. See wait_until_stopped().
        self._running = False

    def wait_until_stopped(self, timeout_ms: int = 1000):
        self.wait(timeout_ms)

    def run(self):
        while self._running and self._manager.is_open():
            try:
                chunk = self._manager.read(256)
            except Exception as e:
                self.error.emit(f"Read failed: {e}")
                break
            if chunk:
                self.raw_rx.emit(chunk)
                try:
                    frames = self._parser.feed(chunk)
                except Exception as e:
                    self.error.emit(f"Frame parse error: {e}")
                    continue
                for f in frames:
                    self.frame_received.emit(f)
