"""Manual discovery tool: which Modbus slave address does each connected
XY-MD02 temp/humidity sensor actually answer on the wire?

use_sensor.py only ever talks to a single hardcoded SENSOR_SLAVE_ADDR (1) -
there's no per-unit addressing yet. Before that can happen, each unit's
real wired address needs to be known - real wiring may not be sequential
(same caveat as the C rewrite's UNIT_TEMP_ADDR table). Run this with one
sensor connected at a time (or several on a shared RS-485 bus) and it
reports which address(es) actually respond, plus their current reading
as a sanity check that it's a live sensor and not noise.

Usage: python -m services.scan_sensor_addresses [PORT] [--start N] [--end N]
If PORT is omitted, lists available ports and prompts.
"""
import argparse
import sys
import time

import serial
import serial.tools.list_ports

from services.modbus import build_read_input_registers, parse_read_input_registers_response, ModbusError
from hooks.use_sensor import (
    SENSOR_START_REGISTER, SENSOR_REGISTER_COUNT, SENSOR_BAUD,
    SENSOR_PARITY, SENSOR_DATA_BITS, SENSOR_READ_TIMEOUT_S, _EXPECTED_RESPONSE_LEN,
)

DEFAULT_SCAN_START = 1
DEFAULT_SCAN_END = 16  # matches MAX_CHANNELS - widen with --end if the real
                        # wiring might use addresses outside this range


def pick_port() -> str:
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if not ports:
        sys.exit("No serial ports found.")
    if len(ports) == 1:
        return ports[0]
    print("Available ports:")
    for i, p in enumerate(ports):
        print(f"  {i}: {p}")
    idx = int(input("Pick a port: ").strip())
    return ports[idx]


def scan(port_name: str, start: int, end: int) -> list[tuple[int, float, float]]:
    ser = serial.Serial(
        port_name, baudrate=SENSOR_BAUD, bytesize=SENSOR_DATA_BITS,
        parity=SENSOR_PARITY, stopbits=serial.STOPBITS_ONE,
        timeout=SENSOR_READ_TIMEOUT_S, write_timeout=SENSOR_READ_TIMEOUT_S,
    )
    try:
        ser.rts = False
        ser.dtr = True
    except Exception:
        pass

    found = []
    print(f"Scanning addresses {start}-{end} on {port_name}...\n")
    for addr in range(start, end + 1):
        request = build_read_input_registers(addr, SENSOR_START_REGISTER, SENSOR_REGISTER_COUNT)
        try:
            ser.reset_input_buffer()
            ser.write(request)
            response = ser.read(_EXPECTED_RESPONSE_LEN)
            registers = parse_read_input_registers_response(response, addr, SENSOR_REGISTER_COUNT)
            temp_c = registers[0] / 10.0
            humidity_pct = registers[1] / 10.0
            print(f"  address {addr:3d}: FOUND  - {temp_c:.1f} C, {humidity_pct:.1f}% RH")
            found.append((addr, temp_c, humidity_pct))
        except ModbusError:
            print(f"  address {addr:3d}: no reply")
        time.sleep(0.05)  # let the bus settle between addresses

    ser.close()
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?", default=None)
    parser.add_argument("--start", type=int, default=DEFAULT_SCAN_START)
    parser.add_argument("--end", type=int, default=DEFAULT_SCAN_END)
    args = parser.parse_args()

    port_name = args.port or pick_port()
    found = scan(port_name, args.start, args.end)

    print(f"\n{len(found)} sensor(s) responded:")
    for addr, temp_c, humidity_pct in found:
        print(f"  address {addr}: {temp_c:.1f} C, {humidity_pct:.1f}% RH")
    if not found:
        print("  (none)")


if __name__ == "__main__":
    main()
