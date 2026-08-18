import os
import sys

if not sys.platform.startswith("win"):
    sys.exit("This only runs on Windows - Transit.dll is a native Windows DLL.")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.middleware import dll_command_tokens

KNOWN_TABLE = {
    b"\x00": "X#0",
    b"\x01": "X#A",
    b"\x02": "X#B",
    b"\x03": "X#C",
    b"\x04": "X#D",
    b"\x05": "X#E",
    b"\x06": "X#F",
    b"\x07": "X#G",
    b"\x08": "X#H",
    b"\x09": "X#I",
    b"\x0a": "X#J",
    b"\x0b": "X#K",
    b"\x0c": "X#L",
    b"\x0d": "X#M",
    b"\x0e": "X#N",
    b"\x0f": "X#O",
    b"\x10": "X#P",
    b"\x7e": "XME",
    b"\xff": "XOP",
    b"\xd0": "X#X",
    b"\xd1": "XHT",
    b"\xd2": "XGY",
}

print(f"Testing all {len(KNOWN_TABLE)} entries found in the DLL's table.\n")
matches = 0
for raw, expected_code in KNOWN_TABLE.items():
    value, error = dll_command_tokens(raw)
    if value is None:
        print(f"  byte {raw.hex().upper()}: CALL FAILED - {error}")
        continue
    try:
        decoded = bytes.fromhex(value.replace(' ', '')).decode('ascii', errors='replace')
    except ValueError:
        decoded = "(not valid hex?)"
    match = "MATCH" if decoded.rstrip('\x00') == expected_code else "no match"
    if match == "MATCH":
        matches += 1
    print(f"  byte {raw.hex().upper()}: got {decoded!r} (raw hex: {value})  expected {expected_code!r}  [{match}]")

print(f"\n{matches}/{len(KNOWN_TABLE)} entries matched exactly.")
