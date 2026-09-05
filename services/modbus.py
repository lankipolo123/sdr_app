"""Modbus RTU framing for the amplifier temperature/humidity sensor.

This is a completely separate, raw serial connection from the RS-422/
Transit.dll channel bus above - a second USB-RS485 adapter running a
real Modbus RTU slave (an XY-MD02 temp/humidity module), confirmed
against real hardware in the C rewrite (digital-noise-configuration-
multi's PLAN_temp_sensor.md): slave address 1, function 0x04 (Read
Input Registers), starting register 1, count 2 (temperature, humidity),
both values raw/10.

Pure protocol logic, no I/O - kept separate from use_sensor.py the same
way the C app splits modbus.c (framing) from sensor.c (the serial state
machine), so the framing can be unit-tested without a real port.
"""


def crc16(data: bytes) -> int:
    """Standard Modbus CRC16 (poly 0xA001, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_read_input_registers(slave_addr: int, start_register: int, count: int) -> bytes:
    body = bytes([
        slave_addr & 0xFF,
        0x04,
        (start_register >> 8) & 0xFF, start_register & 0xFF,
        (count >> 8) & 0xFF, count & 0xFF,
    ])
    crc = crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class ModbusError(Exception):
    """Raised for anything short of a fully valid, CRC-clean response -
    including "not enough bytes yet" (a normal, non-fatal outcome when
    the sensor just hasn't answered this cycle)."""


def parse_read_input_registers_response(data: bytes, slave_addr: int, count: int) -> list[int]:
    expected_len = 3 + count * 2 + 2  # addr + func + byte_count + data + crc16
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
