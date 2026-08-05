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
        # Waits HERE, before the caller closes the port. A prior version
        # tried closing first to avoid this wait, but that let the port
        # get closed from the main thread while this thread could still
        # be mid-read() on the same handle - a real race (not just a
        # theoretical one: SerialManager.read() checks is_open() then
        # touches self._port in two separate steps, and self._port can
        # turn None in between if close() runs concurrently), which can
        # leave the OS-level port handle in a state where reopening it
        # fails. Correctness here matters more than the read's timeout
        # (already a short 0.2s - see SerialManager) occasionally adding
        # a brief, bounded wait.
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
