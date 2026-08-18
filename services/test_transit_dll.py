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
from services.team_vocab import (
    HEAD_TOKEN, STOP_TOKEN, TYPE_TOKENS, OUTPUT_TOKENS, MODE_TOKENS,
    BANDWIDTH_TOKENS, RESP_TOKENS, LEVEL_TOKENS,
)

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


def test_command_tokens_team_vocab():
    """Both real SendCommandToSDR attempts (raw frame bytes, and the
    same frame hex-encoded) returned -2 - the same failure code either
    way, which rules out null-byte truncation as the cause (the
    hex-encoded attempt has zero null bytes and still failed
    identically). That points at content, not encoding: SendCommandToSDR
    may only accept output that's already been through CommandTokens,
    not a raw protocol frame at all - matching the function names
    themselves (CommandTokens = "Translate Tokens" on the whiteboard,
    feeding SendCommandToSDR next) and matching what you said you made
    the FME/NOX/etc vocabulary FOR: CommandTokens' real input, not a
    display-only scheme.

    Every CommandTokens probe so far (services/test_command_tokens.py)
    only tried single raw hex bytes (0x00-0x10 etc), never your actual
    multi-character token strings. This tries those instead - every
    token from services/team_vocab.py, one at a time, as plain ASCII
    text (e.g. b"NOX", b"FME"). Fully safe to run even with real
    hardware connected: CommandTokens only translates, per its own
    name and the whiteboard design - it doesn't touch
    SendCommandToSDR or the wire itself.

    A token CommandTokens actually recognizes should come back as
    something other than "??" - if any do, that's the strongest lead
    yet on what SendCommandToSDR expects as input."""
    tokens = {
        "HEAD": HEAD_TOKEN,
        "STOP": STOP_TOKEN,
        **{f"TYPE({hex(k)})": v for k, v in TYPE_TOKENS.items()},
        **{f"OUTPUT({hex(k)})": v for k, v in OUTPUT_TOKENS.items()},
        **{f"MODE({hex(k)})": v for k, v in MODE_TOKENS.items()},
        **{f"BW({mhz}MHz)": v for mhz, v in BANDWIDTH_TOKENS.items()},
        **{f"RESP({hex(k)})": v for k, v in RESP_TOKENS.items()},
        **{f"LEVEL({lvl})": v for lvl, v in LEVEL_TOKENS.items()},
    }
    for label, token in tokens.items():
        out = ctypes.create_string_buffer(256)
        result = dll.CommandTokens(token.encode(), out, ctypes.sizeof(out))
        print(f"  {label} = {token!r} -> return={result}, buffer={out.value!r}")


def test_send_command(command: bytes = b"TEST"):
    # Also a placeholder - real usage almost certainly needs a
    # successful AutoConnectSDR first, and a real command string in
    # whatever format CommandTokens is meant to produce.
    result = dll.SendCommandToSDR(command, len(command))
    print(f"SendCommandToSDR({command!r}) -> return={result}")
    return result


def test_send_real_status_query(addr: int = 5):
    """Sends a REAL, well-formed Status Query frame (services/protocol/
    commands.py's query_status()) through SendCommandToSDR, using its
    already-declared (char* command, long length) signature - the same
    raw-buffer-plus-length shape AutoConnectSDR/CheckConnection/
    DisconnectSDR already use, and the exact same raw bytes pyserial
    already writes today (see services/serial/serial_thread.py). This
    is the most direct, least-invented guess available for what
    SendCommandToSDR expects - not a wild guess, just the one shape its
    own already-declared argtypes support.

    Defaults to addr=5, a REAL channel, not 0 - every prior test used
    query_status()'s old default of 0, and the whiteboard's SDR module
    diagram labels modules SDR1 through SDR16, no SDR0. If address 0
    isn't a real module, the whiteboard's own "Validate command before
    send to SDR" step would reject it every time regardless of content
    - which would explain why raw bytes, hex-encoded, and translated
    content all failed with the identical -2. Worth ruling out before
    trusting any conclusion drawn from the addr=0 attempts.

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


def test_send_real_status_query_hex(addr: int = 5):
    """Same real Status Query frame as test_send_real_status_query()
    (addr=5, a real channel, not the old addr=0 default - see that
    function's docstring for why), but hex-encoded and uppercased
    first (frame.hex().upper().encode()) instead of sent as raw
    binary - the same fix already confirmed
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


def translate_frame_via_dll(frame: bytes) -> str:
    """Runs CommandTokens once per byte of `frame` (its confirmed,
    only-ever-one-byte-per-call shape - see services/middleware.py's
    dll_decode_frame(), same idea, duplicated here rather than
    imported so this script keeps working standalone) and concatenates
    the results with no separator - CommandTokens' own outputs are
    short fixed-width codes (X#B, XME, ...), so a plain concatenation
    is the most direct guess at what a translated command string looks
    like, no space character invented that was never observed
    anywhere in the DLL's own output."""
    tokens = []
    for byte in frame:
        out = ctypes.create_string_buffer(256)
        dll.CommandTokens(bytes([byte]).hex().upper().encode(), out, ctypes.sizeof(out))
        tokens.append(out.value.decode('ascii', errors='replace'))
    return "".join(tokens)


def test_send_translated_status_query(addr: int = 5):
    """The lead from CommandTokens/SendCommandToSDR's own names (the
    whiteboard's "Translate Tokens" -> "Send to SDR" pipeline): rather
    than sending the raw Status Query frame (confirmed failing, -2,
    both as raw bytes and hex-encoded - see the two probes above),
    this sends what CommandTokens itself produces for that frame -
    e.g. "XMEXMEX#CX#0X#0X#JX#M" for a real 7-byte Status Query -
    exactly the translated form these two function names suggest
    SendCommandToSDR is meant to receive next.

    UPDATE: a later whiteboard photo (TOKENS legend: X#0=0, X#1=1,
    ... right next to "Select what SDR number") suggests CommandTokens
    actually only translates WHICH MODULE a command targets, not every
    byte of its content - see test_send_addr_token_plus_real_command()
    below for that alternative theory, tried separately rather than
    replacing this one, since neither is confirmed yet."""
    frame = query_status(addr)
    translated = translate_frame_via_dll(frame)
    print(f"CommandTokens-translated Status Query: {translated!r}")
    command = translated.encode()
    result = dll.SendCommandToSDR(command, len(command))
    print(f"SendCommandToSDR(<translated status query>) -> return={result}")
    return result


def test_send_addr_token_plus_real_command(addr: int = 5):
    """Alternative theory to test_send_translated_status_query() above,
    from the whiteboard: the TOKENS legend (X#0=0, X#1=1, ...) sits
    right next to "Select what SDR number", not next to the command
    content - CommandTokens translates WHICH module a command targets,
    not the command's bytes. That fits the confirmed data better too:
    the real table only covers 0x00-0x10 (0-16, exactly MAX_CHANNELS),
    and the same raw byte (e.g. 0x01) is simultaneously
    TYPE_OUTPUT_SWITCH, OUTPUT_ON, MODE_LINEAR_SWEEP, and RESP_FAILED
    in the real protocol - one flat table translating every byte could
    never disambiguate those; translating just the address field can.

    So this translates ONLY the address byte through CommandTokens
    (confirmed working, e.g. 0x05 -> "X#E"), then sends that token
    followed by the REST of the real frame UNTRANSLATED (type,
    buf_len, payload, STOP - left as real bytes, address byte
    dropped since it's now represented by the token instead) - i.e.
    "address swapped for its token, the actual command stays real."
    Exact placement (token prepended to the front) is still a guess -
    the whiteboard doesn't show the wire format for the combined
    message, just that translation and command content are separate
    concerns."""
    frame = query_status(addr)
    out = ctypes.create_string_buffer(256)
    dll.CommandTokens(frame[3:4].hex().upper().encode(), out, ctypes.sizeof(out))
    addr_token = out.value.decode('ascii', errors='replace')
    command = addr_token.encode() + frame[:3] + frame[4:]
    print(f"Sending addr-token({addr_token!r}) + rest of real frame: {command!r}")
    result = dll.SendCommandToSDR(command, len(command))
    print(f"SendCommandToSDR(<addr-token + real frame>) -> return={result}")
    return result


if __name__ == "__main__":
    print(f"Loaded {DLL_PATH} OK\n")
    print("Step 1: connect")
    connect_result = test_auto_connect()
    print("\nStep 2: check status")
    test_check_connection()

    # Safe regardless of connection state - CommandTokens only
    # translates, per its own name and the whiteboard design, it
    # doesn't touch the wire or SendCommandToSDR itself.
    print("\nStep 2b: probe CommandTokens with the real FME/NOX/etc team vocabulary")
    test_command_tokens_team_vocab()

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
            print(
                "\nStep 4c: CommandTokens-translated (Step 2b confirmed CommandTokens "
                "only recognizes real protocol bytes, not the FME/NOX vocabulary - "
                "this sends ITS translated output, not the raw frame)"
            )
            test_send_translated_status_query()
            print(
                "\nStep 4d: address-token + real command (whiteboard theory - "
                "CommandTokens only translates WHICH module, not the command "
                "content - see test_send_addr_token_plus_real_command()'s docstring)"
            )
            test_send_addr_token_plus_real_command()
            print("\nStep 4e: check status again - compare this buffer to Step 2's by eye")
            test_check_connection()
        else:
            print("Skipped - no real command sent.")

    print("\nStep 5: disconnect")
    test_disconnect()
