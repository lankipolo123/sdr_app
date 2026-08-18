import struct
from . import constants as c


class ProtocolError(ValueError):
    pass


def _frame(type_byte: int, addr: int, buf: bytes) -> bytes:
    if not (0 <= addr <= 0xFF):
        raise ProtocolError(f"Address out of range: {addr}")
    if len(buf) > 0xFF:
        raise ProtocolError("Payload too long for 1-byte BufLen field")
    return (
        c.HEAD
        + bytes([type_byte, addr, len(buf)])
        + buf
        + c.STOP
    )


def build_output_switch(addr: int, on: bool) -> bytes:
    buf = bytes([c.OUTPUT_ON if on else c.OUTPUT_OFF])
    return _frame(c.TYPE_OUTPUT_SWITCH, addr, buf)


def build_signal_control(addr: int, mode: int, freq_mhz: int,
                          bandwidth_mhz: int, power_code: int) -> bytes:
    if mode not in c.MODE_NAMES:
        raise ProtocolError(f"Unknown mode: {mode}")
    if not (c.FREQ_MIN_MHZ <= freq_mhz <= c.FREQ_MAX_MHZ):
        raise ProtocolError(
            f"Frequency {freq_mhz} MHz out of range "
            f"({c.FREQ_MIN_MHZ}-{c.FREQ_MAX_MHZ})"
        )
    if bandwidth_mhz not in c.BANDWIDTH_CODES:
        raise ProtocolError(f"Unsupported bandwidth: {bandwidth_mhz} MHz")
    if not (0 <= power_code <= 0xFF):
        raise ProtocolError(f"Power code out of range for a single byte: {power_code}")

    buf = bytes([mode]) \
        + struct.pack(">H", freq_mhz) \
        + bytes([c.BANDWIDTH_CODES[bandwidth_mhz]]) \
        + bytes([power_code])
    return _frame(c.TYPE_SIGNAL_CONTROL, addr, buf)


def build_status_query(addr: int = 0x00) -> bytes:
    return _frame(c.TYPE_STATUS_QUERY, addr, b"")


def build_addr_query() -> bytes:
    return _frame(c.TYPE_ADDR_QUERY, c.BROADCAST_ADDR, b"")


def build_addr_set(new_addr: int) -> bytes:
    if not (c.ADDR_MIN <= new_addr <= c.ADDR_MAX):
        raise ProtocolError(f"Address out of range: {new_addr}")
    return _frame(c.TYPE_ADDR_SET, c.BROADCAST_ADDR, bytes([new_addr]))
