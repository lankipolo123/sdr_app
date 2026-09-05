"""Exercises the amplifier temperature sensor and kill-switch logic
against fake serial hardware - no real port needed. Run directly:
python -m tests.test_sensor (or python tests/test_sensor.py from repo root).

Mirrors the fake_hardware.py pattern already used for the Transit.dll
side (fake_hardware.py / install_fake_dll): a small stand-in object
swapped in for the real dependency, not a mocking framework.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hooks.use_sensor as use_sensor
from hooks.use_safety import SafetyController, KILL_SWITCH_THRESHOLD_C
from services.modbus import build_read_input_registers, parse_read_input_registers_response, ModbusError

# Real hardware capture (see the C rewrite's PLAN_temp_sensor.md /
# modbus test vectors) - slave 1, function 0x04, register 1, count 2 ->
# 28.1 C / 35.9%.
REAL_REQUEST = bytes.fromhex("010400020002D00B")
REAL_RESPONSE = bytes.fromhex("01040401190167" "6BC5")


class _FakeSerialOK:
    def __init__(self, *a, **kw):
        self.rts = None
        self.dtr = None

    def reset_input_buffer(self): pass
    def reset_output_buffer(self): pass
    def write(self, data): self.last_written = data
    def read(self, n): return REAL_RESPONSE[:n]
    def close(self): pass


class _FakeSerialDead:
    def __init__(self, *a, **kw):
        self.rts = None
        self.dtr = None

    def reset_input_buffer(self): pass
    def reset_output_buffer(self): pass
    def write(self, data): raise OSError("device disconnected")
    def read(self, n): raise OSError("device disconnected")
    def close(self): pass


class _FakeSerialModule:
    STOPBITS_ONE = 1

    def __init__(self, cls):
        self._cls = cls

    def Serial(self, *a, **kw):
        return self._cls(*a, **kw)


class _FakeChannelController:
    def __init__(self):
        self.off_calls = 0

    def turn_output_off(self):
        self.off_calls += 1


class _FakeChannelManager:
    def __init__(self, n):
        self.controllers = [_FakeChannelController() for _ in range(n)]

    def get_controller(self, address):
        return self.controllers[address]


def test_modbus_framing():
    req = build_read_input_registers(1, 2, 2)
    assert req == REAL_REQUEST, req.hex()

    registers = parse_read_input_registers_response(REAL_RESPONSE, 1, 2)
    assert registers == [281, 359], registers

    try:
        parse_read_input_registers_response(REAL_RESPONSE[:5], 1, 2)
        raise AssertionError("should have raised on a truncated response")
    except ModbusError:
        pass

    corrupted = bytearray(REAL_RESPONSE)
    corrupted[-1] ^= 0xFF
    try:
        parse_read_input_registers_response(bytes(corrupted), 1, 2)
        raise AssertionError("should have raised on a bad CRC")
    except ModbusError:
        pass

    print("test_modbus_framing OK")


def test_sensor_reads_and_disconnects_on_hard_error():
    use_sensor.serial = _FakeSerialModule(_FakeSerialOK)
    sensor = use_sensor.SensorController()
    assert sensor.connect("COM9")
    time.sleep(0.2)
    sensor._timer.stop()  # don't let the next poll fire mid-assert

    state = sensor.get_state()
    assert state["has_reading"] is True
    assert state["online"] is True
    assert abs(state["temperature_c"] - 28.1) < 1e-6
    assert abs(state["humidity_pct"] - 35.9) < 1e-6
    assert state["last_rx_len"] == 9

    use_sensor.serial = _FakeSerialModule(_FakeSerialDead)
    sensor2 = use_sensor.SensorController()
    assert sensor2.connect("COM9")
    time.sleep(0.2)
    assert sensor2.is_connected() is False, "a hard write/read error must disconnect, not just log"

    print("test_sensor_reads_and_disconnects_on_hard_error OK")


def test_kill_switch():
    channels = _FakeChannelManager(16)
    safety = SafetyController(channels)
    events = []
    safety.tripped_changed.connect(events.append)

    safety.on_sensor_state({"has_reading": True, "temperature_c": KILL_SWITCH_THRESHOLD_C - 0.1})
    assert safety.tripped is False

    safety.on_sensor_state({"has_reading": True, "temperature_c": KILL_SWITCH_THRESHOLD_C})
    assert safety.tripped is True
    assert all(c.off_calls == 1 for c in channels.controllers)
    assert events == [True]

    # Manual-reset-only: dipping back under the threshold must not clear it.
    safety.on_sensor_state({"has_reading": True, "temperature_c": 40.0})
    assert safety.tripped is True

    safety.reset()
    assert safety.tripped is False
    assert events == [True, False]

    print("test_kill_switch OK")


if __name__ == "__main__":
    test_modbus_framing()
    test_sensor_reads_and_disconnects_on_hard_error()
    test_kill_switch()
    print("ALL TESTS PASSED")
