"""Stands in for real serial hardware so the full app stack (discovery,
command round-trips, protocol framing, reactive UI sync) can be exercised
without a physical module attached. Used by tests/dry_run.py.

FakeModulePort parses whatever the app writes to it with the same
FrameParser the app itself uses, and answers with protocol-correct
response frames - so everything above the serial byte stream (
ConnectionController, SerialThread, ChannelController, the UI) runs
completely for real against synthetic traffic, not mocked out.
"""
import struct
import time

from services.protocol import constants as c
from services.protocol.packet_parser import FrameParser


class FakeModulePort:
    """One simulated hardware module. Each instance is one point-to-point
    RS422 link's worth of state, matching how the real modules behave
    (confirmed on real hardware: they don't share a bus)."""

    def __init__(self, address: int = 0, mode: int = c.MODE_WHITE_NOISE,
                 freq_mhz: int = 2450, bandwidth_mhz: int = 100, power_db: int = 0,
                 output_on: bool = False, silent: bool = False):
        self.address = address
        self.mode = mode
        self.freq_mhz = freq_mhz
        self.bandwidth_mhz = bandwidth_mhz
        self.power_db = power_db
        self.output_on = output_on
        # Never replies to anything - simulates a dead port (nothing
        # plugged in, or a module that's stopped answering mid-session)
        # for testing discovery-timeout and command-timeout handling.
        self.silent = silent
        self._parser = FrameParser()
        self._rx = bytearray()  # queued module -> app bytes

    def write(self, data: bytes):
        if self.silent:
            return
        for frame in self._parser.feed(data):
            self._handle(frame)

    def read(self, size: int = 256) -> bytes:
        if not self._rx:
            time.sleep(0.005)  # avoid a hot-spinning read loop like real pyserial's timeout would
            return b""
        chunk = bytes(self._rx[:size])
        del self._rx[:size]
        return chunk

    def _reply(self, frame_type: int, payload: bytes):
        self._rx.extend(c.HEAD + bytes([frame_type, self.address, len(payload)]) + payload + c.STOP)

    def _handle(self, frame):
        if frame.type == c.TYPE_ADDR_QUERY:
            self._reply(c.TYPE_ADDR_QUERY, bytes([self.address]))
        elif frame.type == c.TYPE_STATUS_QUERY:
            payload = (
                bytes([int(self.output_on), self.mode])
                + struct.pack(">H", self.freq_mhz)
                + bytes([c.BANDWIDTH_CODES[self.bandwidth_mhz], c.POWER_CODES[self.power_db]])
            )
            self._reply(c.TYPE_STATUS_QUERY, payload)
        elif frame.type == c.TYPE_OUTPUT_SWITCH and frame.addr == self.address:
            self.output_on = frame.buf[0] == c.OUTPUT_ON
            self._reply(c.TYPE_OUTPUT_SWITCH, bytes([c.RESP_SUCCESS]))
        elif frame.type == c.TYPE_SIGNAL_CONTROL and frame.addr == self.address:
            self.mode = frame.buf[0]
            self.freq_mhz = struct.unpack(">H", frame.buf[1:3])[0]
            self.bandwidth_mhz = c.BANDWIDTH_CODES_REV[frame.buf[3]]
            self.power_db = c.POWER_CODES_REV[frame.buf[4]]
            # Deliberately does NOT set self.output_on here - matches real
            # hardware (confirmed via spectrum analyzer): Signal Control
            # alone reconfigures parameters but doesn't re-enable the RF
            # stage once it's been switched off. Only Output Switch ON
            # does that. Without this, the fake would have hidden the
            # exact bug that was found on real hardware.
            self._reply(c.TYPE_SIGNAL_CONTROL, bytes([c.RESP_SUCCESS]))


class FakePortRegistry:
    """What's "plugged in" for a test run - maps fake port names to
    FakeModulePort instances, the same way real ports map to real
    modules."""

    def __init__(self):
        self.modules: dict[str, FakeModulePort] = {}

    def add(self, port_name: str, module: FakeModulePort):
        self.modules[port_name] = module

    def list_ports(self):
        return list(self.modules.keys())


class FakeSerialManager:
    """Drop-in replacement for services.serial.serial_manager.SerialManager."""

    def __init__(self, registry: FakePortRegistry):
        self._registry = registry
        self._module: FakeModulePort | None = None
        self._open = False

    def open(self, port_name: str, baud: int = 115200, parity: str = "N", data_bits: int = 8):
        if port_name not in self._registry.modules:
            raise RuntimeError(f"no fake module on {port_name!r}")
        self._module = self._registry.modules[port_name]
        self._open = True

    def close(self):
        self._open = False
        self._module = None

    def is_open(self) -> bool:
        return self._open

    def write(self, data: bytes):
        if not self._open:
            raise RuntimeError("port not open")
        self._module.write(data)

    def read(self, size: int = 256) -> bytes:
        if not self._open:
            return b""
        return self._module.read(size)


def install_fake_hardware(registry: FakePortRegistry):
    """Reroutes the app's serial layer to the given fake registry. Patches
    the names as imported into hooks/use_connection.py and
    hooks/use_discovery.py (Python binds those at import time, so the
    real modules are untouched - only these two modules' local
    references change for the life of the test process)."""
    import hooks.use_connection as uc
    import hooks.use_discovery as ud

    uc.SerialManager = lambda: FakeSerialManager(registry)
    uc.list_com_ports = registry.list_ports
    ud.list_com_ports = registry.list_ports
