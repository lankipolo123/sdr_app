"""Isolated, one-shot test of Transit.dll's CommandTokens - run this ON
WINDOWS, from the repo root, with the DLL at dll/Transit.dll:

    python services/test_command_tokens.py

WHY THIS TEST LOOKS THE WAY IT DOES

Earlier tests fed CommandTokens a whole 8-byte command frame (hex-
encoded, e.g. "7E7E010101010A0D" for Output ON channel 1) and always
got back "??" (3F 3F) - "unrecognized", even though every individual
byte in that frame is a value the DLL clearly knows about.

Disassembling CommandTokens found out why: its lookup table, read
directly out of the DLL's own .rdata section, only has ONE match/no-
match check for the ENTIRE input string - not a scan across the string
matching multiple bytes. And every key in that table is exactly 2 hex
characters (one byte):

    00->X#0  01->X#A  02->X#B  03->X#C  04->X#D  05->X#E  06->X#F
    07->X#G  08->X#H  09->X#I  0A->X#J  0B->X#K  0C->X#L  0D->X#M
    0E->X#N  0F->X#O  10->X#P  7E->XME  FF->XOP  D0->X#X  D1->XHT
    D2->XGY

A 16-character frame string can never equal a 2-character key, no
matter how many of its individual bytes appear in the table - so the
whole-frame test was never going to succeed. This test instead sends
ONE byte at a time (exactly what the table's keys look like), to
confirm CommandTokens actually works for input it's built to recognize.

This test only checks the exact table entries found by disassembly
against the DLL's actual output - nothing about what these codes mean
is asserted here, only whether the DLL returns them.
"""
import os
import sys

if not sys.platform.startswith("win"):
    sys.exit("This only runs on Windows - Transit.dll is a native Windows DLL.")

# Running this file directly (python services\test_command_tokens.py)
# only puts services\ itself on sys.path, not the project root - so
# "services.middleware" can't be found from inside the services
# package. Add the root explicitly, same fix tests/dry_run.py already
# has, so this runs the same way regardless of how it's invoked.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.middleware import dll_command_tokens

# The complete table found in the DLL's own .rdata section - every key
# it has, not a sample. Expected outputs are the exact values sitting
# right next to each key in the binary, so this test knows what
# "correct" looks like for every entry that exists, not just some of
# them.
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
    # value comes back as hex-of-the-response-bytes (e.g. "58 23 4D" for "X#M") -
    # decode it back to text for an easy side-by-side comparison.
    try:
        decoded = bytes.fromhex(value.replace(' ', '')).decode('ascii', errors='replace')
    except ValueError:
        decoded = "(not valid hex?)"
    match = "MATCH" if decoded.rstrip('\x00') == expected_code else "no match"
    if match == "MATCH":
        matches += 1
    print(f"  byte {raw.hex().upper()}: got {decoded!r} (raw hex: {value})  expected {expected_code!r}  [{match}]")

print(f"\n{matches}/{len(KNOWN_TABLE)} entries matched exactly.")
