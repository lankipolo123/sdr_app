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
        self._running = False
        self.wait(1000)

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
