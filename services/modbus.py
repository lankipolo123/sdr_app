"""Modbus RTU framing for the amplifier temperature/humidity sensors - a
completely separate, raw serial connection from the RS-422/Transit.dll
bus the channel cards use (services/middleware.py). Pure protocol logic,
no I/O, so it can be unit-tested without a real port - same split as the
channel protocol's services/protocol/ package.

Confirmed against a real XY-MD02 temp/humidity module (see the C
rewrite's src/sensor.c and its own PLAN_temp_sensor.md): function 0x04
(Read Input Registers), starting register 1, count 2, both values
raw/10.
"""

START_REGISTER = 1
REGISTER_COUNT = 2
# addr + func + byte_count + 2 registers * 2 bytes + crc16
EXPECTED_RESPONSE_LEN = 3 + REGISTER_COUNT * 2 + 2


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_read_input_registers(slave_addr: int, start_register: int = START_REGISTER,
                                count: int = REGISTER_COUNT) -> bytes:
    body = bytes([
        slave_addr & 0xFF,
        0x04,
        (start_register >> 8) & 0xFF,
        start_register & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ])
    crc = crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class ModbusError(ValueError):
    pass


def parse_read_input_registers_response(data: bytes, slave_addr: int,
                                         count: int = REGISTER_COUNT) -> list[int]:
    """Raises ModbusError for anything short of a fully valid, CRC-clean
    response - including "not enough bytes yet", a normal, non-fatal
    outcome when the sensor just hasn't answered this cycle."""
    expected_len = 3 + count * 2 + 2
    if len(data) < expected_len:
        raise ModbusError(f"incomplete response ({len(data)}/{expected_len} bytes)")

    frame = data[:expected_len]

    if frame[0] != slave_addr:
        raise ModbusError(f"unexpected slave address {frame[0]}")
    if frame[1] == (0x04 | 0x80):
        raise ModbusError(f"device returned exception code {frame[2]}")
    if frame[1] != 0x04:
        raise ModbusError(f"unexpected function code {frame[1]}")
    if frame[2] != count * 2:
        raise ModbusError(f"unexpected byte count {frame[2]}")

    received_crc = frame[-2] | (frame[-1] << 8)
    computed_crc = crc16(frame[:-2])
    if received_crc != computed_crc:
        raise ModbusError("CRC mismatch")

    return [
        (frame[3 + i * 2] << 8) | frame[3 + i * 2 + 1]
        for i in range(count)
    ]
