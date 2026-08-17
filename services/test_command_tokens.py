"""Isolated, one-shot test of Transit.dll's CommandTokens - run this ON
WINDOWS, from the repo root, with the DLL at dll/Transit.dll:

    python services/test_command_tokens.py

Builds a REAL Output ON frame using the app's own proven command
builder (services/protocol/commands.py - not hand-typed, guaranteed
byte-accurate) for a channel that isn't currently connected, so this
never touches real hardware - it only calls CommandTokens (translate),
never SendCommandToSDR (transmit).

Every byte in a plain Output ON/OFF frame (7E, 01, 0A, 0D) is inside
the lookup table found by disassembling the DLL (see services/
middleware.py's dll_command_tokens() docstring) - this is the cleanest
possible test of whether CommandTokens actually translates a real
command instead of falling back to "??" (unrecognized input).
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
from services.protocol.commands import output_on

frame = output_on(1)  # address 1 - a plain Output ON frame, nothing else
print("Real frame (from the app's own command builder):", frame.hex(' ').upper())
print("Every byte in this frame is inside the table found in the DLL's own .rdata section.\n")

value, error = dll_command_tokens(frame)
if value is not None:
    print("CommandTokens translated it successfully:")
    print("  ", value)
else:
    print("CommandTokens call failed or DLL unavailable:")
    print("  ", error)
