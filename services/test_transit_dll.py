"""Manual test harness for Transit.dll - run this ON WINDOWS with a
Python interpreter matching the DLL's own bitness (confirm with `file`/
pefile - a 64-bit Python process cannot load a 32-bit DLL or vice versa).

AutoConnectSDR/CheckConnection/DisconnectSDR's signatures - a string
buffer + a length, returning a status code - are now CONFIRMED working
against the real 64-bit DLL (loaded clean, no crash, sensible output:
AutoConnectSDR returned -1/"DisConnected" with no real hardware
attached, exactly the expected behavior). AutoConnectSDR's shape was
originally taken from the VB6 Declare statement:
    Private Declare Function AutoConnectSDR Lib "dll\\Transit.dll" _
        (ByVal outBuffer As String, ByVal maxLength As Long) As Long

CommandTokens and SendCommandToSDR are still UNCONFIRMED GUESSES -
CommandTokens especially, since its real input format (whatever token
vocabulary ends up finalized) isn't settled yet. test_command_tokens()
below just probes it with a placeholder string to see if it crashes or
returns something legible - not a real test of correct behavior until
the actual token format is confirmed.

ctypes.WinDLL (not CDLL) because VB6's plain Declare statement only
ever works against __stdcall exports - CDLL would get the stack
cleanup wrong and likely crash or corrupt the stack on return.
"""
import ctypes
import os
import sys

if not sys.platform.startswith("win"):
    sys.exit("This only runs on Windows - Transit.dll is a native Windows DLL.")

# Running this file directly only puts services\ on sys.path, not the
# project root - needed below for services.protocol.commands.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.protocol.commands import query_status

DLL_PATH = "dll/Transit.dll"  # matches the "dll\Transit.dll" path hardcoded in the original VB6 Declare statement

dll = ctypes.WinDLL(DLL_PATH)

# --- Confirmed from the VB6 Declare ---
dll.AutoConnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.AutoConnectSDR.restype = ctypes.c_long

# --- Guesses - confirm against real docs before trusting these ---
dll.CheckConnection.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.CheckConnection.restype = ctypes.c_long

dll.DisconnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.DisconnectSDR.restype = ctypes.c_long

# CommandTokens is the "Translate Tokens" function from the whiteboard -
# almost certainly takes a token string in and writes a translated
# command into outBuffer, but the exact shape is unconfirmed.
dll.CommandTokens.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long]
dll.CommandTokens.restype = ctypes.c_long

dll.SendCommandToSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.SendCommandToSDR.restype = ctypes.c_long


def test_auto_connect():
    buf = ctypes.create_string_buffer(256)
    result = dll.AutoConnectSDR(buf, ctypes.sizeof(buf))
    print(f"AutoConnectSDR -> return={result}, buffer={buf.value!r}")
    return result


def test_check_connection():
    buf = ctypes.create_string_buffer(256)
    result = dll.CheckConnection(buf, ctypes.sizeof(buf))
    print(f"CheckConnection -> return={result}, buffer={buf.value!r}")
    return result


def test_disconnect():
    buf = ctypes.create_string_buffer(256)
    result = dll.DisconnectSDR(buf, ctypes.sizeof(buf))
    print(f"DisconnectSDR -> return={result}, buffer={buf.value!r}")
    return result


def test_command_tokens(token: bytes = b"TEST"):
    # Placeholder input - the real token vocabulary isn't finalized yet
    # (see services/middleware.py's Token/Action for the current Python-
    # side design). This just checks CommandTokens doesn't crash and
    # shows what comes back for an arbitrary string, not a real
    # correctness test.
    out = ctypes.create_string_buffer(256)
    result = dll.CommandTokens(token, out, ctypes.sizeof(out))
    print(f"CommandTokens({token!r}) -> return={result}, buffer={out.value!r}")
    return result


def test_send_command(command: bytes = b"TEST"):
    # Also a placeholder - real usage almost certainly needs a
    # successful AutoConnectSDR first, and a real command string in
    # whatever format CommandTokens is meant to produce.
    result = dll.SendCommandToSDR(command, len(command))
    print(f"SendCommandToSDR({command!r}) -> return={result}")
    return result


def test_send_real_status_query(addr: int = 0):
    """Sends a REAL, well-formed Status Query frame (services/protocol/
    commands.py's query_status()) through SendCommandToSDR, using its
    already-declared (char* command, long length) signature - the same
    raw-buffer-plus-length shape AutoConnectSDR/CheckConnection/
    DisconnectSDR already use, and the exact same raw bytes pyserial
    already writes today (see services/serial/serial_thread.py). This
    is the most direct, least-invented guess available for what
    SendCommandToSDR expects - not a wild guess, just the one shape its
    own already-declared argtypes support.

    Status Query is read-only - it asks the module for its current
    state, it changes nothing - so this is the safest real command to
    probe the send path with, even against real hardware. It does NOT
    confirm how a response comes back, though: SendCommandToSDR's
    signature has no output buffer, and no DLL export for reading data
    back has been found yet. Call test_check_connection() again after
    this and compare its buffer by eye against what it showed before -
    if it now shows Status Query fields (output/mode/freq/bw/power -
    see ParsedFrame.describe in services/protocol/packet_parser.py),
    that's evidence CheckConnection doubles as the response channel.
    If it's unchanged, sending is confirmed but reading responses back
    through the DLL is still an open question, not a confirmed one."""
    frame = query_status(addr)
    print(f"Sending real Status Query frame: {frame.hex(' ').upper()}")
    result = dll.SendCommandToSDR(frame, len(frame))
    print(f"SendCommandToSDR(<status query frame>) -> return={result}")
    return result


def test_send_real_status_query_hex(addr: int = 0):
    """Same real Status Query frame as test_send_real_status_query(),
    but hex-encoded and uppercased first (frame.hex().upper().encode())
    instead of sent as raw binary - the same fix already confirmed
    necessary for CommandTokens (see dll_command_tokens()'s docstring
    in services/middleware.py): a char* argument across this DLL's ABI
    gets truncated at the first embedded null byte if treated as a C
    string internally, and a real protocol frame like this one
    (7E 7E FF 00 00 0A 0D) has null bytes sitting right in the middle
    (the addr/buf_len fields). Worth trying before concluding anything
    about SendCommandToSDR's real expected format from a raw-bytes
    attempt alone - the raw attempt may have just hit the same
    already-known truncation bug, not a wrong approach."""
    frame = query_status(addr)
    hex_command = frame.hex().upper().encode()
    print(f"Sending hex-encoded Status Query frame: {hex_command!r}")
    result = dll.SendCommandToSDR(hex_command, len(hex_command))
    print(f"SendCommandToSDR(<hex-encoded status query>) -> return={result}")
    return result


if __name__ == "__main__":
    print(f"Loaded {DLL_PATH} OK\n")
    print("Step 1: connect")
    connect_result = test_auto_connect()
    print("\nStep 2: check status")
    test_check_connection()

    # SendCommandToSDR("TEST") is only safe to fire blind when nothing
    # real is on the other end - a placeholder string is exactly the
    # "manipulated/unvalidated command" risk this whole project exists
    # to prevent once real hardware is actually connected. -1 is the
    # observed "nothing connected" return; 4 is now a CONFIRMED
    # "connected" return (buffer=b'Connected', observed against real
    # hardware) - any non--1 value means AutoConnectSDR found something
    # real, not just "not -1".
    if connect_result == -1:
        print("\nStep 3: translate a placeholder token (exploratory - format unconfirmed)")
        test_command_tokens()
        print("\nStep 4: send a placeholder command (exploratory - format unconfirmed)")
        test_send_command()
    else:
        print(
            f"\nAutoConnectSDR returned {connect_result} - something real is connected."
        )
        print(
            "Skipping the placeholder CommandTokens/SendCommandToSDR probes above - "
            "those send an arbitrary made-up string, not a real command, so they're "
            "only safe when nothing real is on the other end."
        )
        print(
            "\nStep 4: probe SendCommandToSDR with a REAL, well-formed, read-only "
            "Status Query frame - once as raw bytes, once hex-encoded (the fix "
            "already confirmed necessary for CommandTokens - see "
            "test_send_real_status_query_hex()'s docstring). A raw-bytes attempt "
            "failing doesn't confirm the format is wrong; it may just be the same "
            "null-byte truncation bug CommandTokens already hit."
        )
        answer = input(
            "Send real Status Query probes to the connected hardware now? [y/N] "
        ).strip().lower()
        if answer == "y":
            print("\nStep 4a: raw bytes")
            test_send_real_status_query()
            print("\nStep 4b: hex-encoded")
            test_send_real_status_query_hex()
            print("\nStep 4c: check status again - compare this buffer to Step 2's by eye")
            test_check_connection()
        else:
            print("Skipped - no real command sent.")

    print("\nStep 5: disconnect")
    test_disconnect()
