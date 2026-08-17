from PySide6.QtCore import QThread, Signal, QCoreApplication

from services.protocol.packet_parser import FrameParser
from .serial_manager import SerialManager

STOP_POLL_MS = 20     # slice size - short enough that the UI stays responsive
STOP_TIMEOUT_MS = 2000  # hard cap - give up waiting rather than hang forever


class SerialThread(QThread):
    """Background read loop for one open serial port - roughly the Qt
    equivalent of a Web Worker: run() executes on its own OS thread so
    a blocking port read never freezes the GUI, and it only ever talks
    back to the rest of the app through the Signals below (frame_received/
    raw_rx/error), never by calling into GUI code directly."""

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
        # fails. Correctness here matters more than waiting.
        #
        # What changed: one long self.wait(1000) call froze the entire
        # UI for however long that took - on a flaky connection, a real
        # read() doesn't reliably respect its own configured 0.2s
        # timeout, so this could run close to the full second with
        # nothing on screen moving, reading as "it's never coming back."
        # Waiting in short slices with processEvents() between each one
        # gets the exact same total wait, just without freezing paint
        # updates and other input while it happens - the button click
        # registers immediately even though the actual disconnect still
        # takes the same real time underneath.
        self._running = False
        elapsed = 0
        while elapsed < STOP_TIMEOUT_MS and not self.wait(STOP_POLL_MS):
            QCoreApplication.processEvents()
            elapsed += STOP_POLL_MS

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
