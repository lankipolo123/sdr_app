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


class SendAttempt:
    """One candidate theory of what SendCommandToSDR actually wants -
    both its argument SIGNATURE and its CONTENT, since both are
    unconfirmed (see this file's module docstring: only AutoConnectSDR's
    shape came from a real VB6 Declare; the rest, including
    SendCommandToSDR's very argument count, were guessed by symmetry).
    `run` sets dll.SendCommandToSDR.argtypes/.restype itself right
    before calling - ctypes allows re-declaring these freely between
    calls on the same underlying export - and returns a plain dict so
    every candidate reports the same shape of result regardless of how
    different its actual call looks, for a clean side-by-side summary
    at the end. Never lets a wrong-signature guess crash the whole
    run: a ctypes.ArgumentError (wrong Python type for the declared
    argtypes) is caught and reported as its own outcome, not a crash."""

    def __init__(self, label: str, reasoning: str, run):
        self.label = label
        self.reasoning = reasoning
        self.run = run  # callable(addr: int) -> dict


def _try_send(argtypes, restype, args) -> dict:
    dll.SendCommandToSDR.argtypes = argtypes
    dll.SendCommandToSDR.restype = restype
    try:
        result = dll.SendCommandToSDR(*args)
        return {"return_code": result, "error": None}
    except Exception as e:
        return {"return_code": None, "error": str(e)}


def _addr_token(addr_byte: bytes) -> str:
    """CommandTokens' translated text for one raw byte - e.g. b'\\x05' -> 'X#E'."""
    out = ctypes.create_string_buffer(256)
    dll.CommandTokens(addr_byte.hex().upper().encode(), out, ctypes.sizeof(out))
    return out.value.decode("ascii", errors="replace")


def _run_raw_bytes_2arg(addr: int) -> dict:
    frame = query_status(addr)
    return _try_send([ctypes.c_char_p, ctypes.c_long], ctypes.c_long, (frame, len(frame)))


def _run_hex_encoded_2arg(addr: int) -> dict:
    content = query_status(addr).hex().upper().encode()
    return _try_send([ctypes.c_char_p, ctypes.c_long], ctypes.c_long, (content, len(content)))


def _run_translated_whole_frame_2arg(addr: int) -> dict:
    content = translate_frame_via_dll(query_status(addr)).encode()
    return _try_send([ctypes.c_char_p, ctypes.c_long], ctypes.c_long, (content, len(content)))


def _run_addr_token_plus_real_2arg(addr: int) -> dict:
    frame = query_status(addr)
    token = _addr_token(frame[3:4])  # byte 3 is the address field - see packet_builder.py
    content = token.encode() + frame[:3] + frame[4:]  # address byte dropped, replaced by its token
    return _try_send([ctypes.c_char_p, ctypes.c_long], ctypes.c_long, (content, len(content)))


def _run_stripped_framing_raw_2arg(addr: int) -> dict:
    content = query_status(addr)[2:-2]  # drop HEAD (first 2 bytes) and STOP (last 2 bytes)
    return _try_send([ctypes.c_char_p, ctypes.c_long], ctypes.c_long, (content, len(content)))


def _run_stripped_framing_hex_2arg(addr: int) -> dict:
    content = query_status(addr)[2:-2].hex().upper().encode()
    return _try_send([ctypes.c_char_p, ctypes.c_long], ctypes.c_long, (content, len(content)))


def _run_3arg_matching_commandtokens_shape(addr: int) -> dict:
    frame = query_status(addr)
    out = ctypes.create_string_buffer(256)
    return _try_send(
        [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long], ctypes.c_long,
        (frame, out, len(frame)),
    )


def _run_addr_as_separate_int_arg(addr: int) -> dict:
    frame = query_status(addr)
    content = frame[:3] + frame[4:]  # HEAD/type/buf_len/payload/STOP, address byte removed
    return _try_send(
        [ctypes.c_long, ctypes.c_char_p, ctypes.c_long], ctypes.c_long,
        (addr, content, len(content)),
    )


def _run_addr_as_separate_string_arg(addr: int) -> dict:
    # Follow-up to _run_addr_as_separate_int_arg: THAT attempt crashed
    # on real hardware with "access violation reading 0x...05" - the
    # DLL tried to dereference our literal address int (5) as a
    # pointer. That's real negative evidence the address parameter (if
    # it exists at all) isn't a plain c_long in that slot - it has to
    # be something pointer-shaped, or the DLL would never have tried
    # to read memory AT the value 5. This tries the address as an
    # actual string pointer instead (e.g. b"5"), all-pointer args like
    # CommandTokens' own confirmed-safe 3-arg shape, to avoid repeating
    # the same crash while still testing "address as its own parameter."
    frame = query_status(addr)
    addr_str = str(addr).encode()
    content = frame[:3] + frame[4:]  # address byte removed, same as the int-arg attempt above
    return _try_send(
        [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long], ctypes.c_long,
        (addr_str, content, len(content)),
    )


SEND_ATTEMPTS = [
    SendAttempt(
        "raw_bytes_2arg",
        "The most direct, least-invented guess: real frame bytes, (char* command, long length) - "
        "the same raw-buffer-plus-length shape AutoConnectSDR/CheckConnection/DisconnectSDR use.",
        _run_raw_bytes_2arg,
    ),
    SendAttempt(
        "hex_encoded_2arg",
        "Same frame, hex-encoded+uppercased first - the fix already confirmed necessary for "
        "CommandTokens (a char* gets truncated at the first embedded null byte if treated as a "
        "C string, and a real frame has null bytes in its addr/buf_len fields).",
        _run_hex_encoded_2arg,
    ),
    SendAttempt(
        "translated_whole_frame_2arg",
        "What CommandTokens itself produces for the whole frame, one byte at a time and joined - "
        "the literal \"Translate Tokens\" -> \"Send to SDR\" pipeline the function names suggest.",
        _run_translated_whole_frame_2arg,
    ),
    SendAttempt(
        "addr_token_plus_real_2arg",
        "Whiteboard theory: CommandTokens only translates WHICH module (its TOKENS legend sits "
        "next to \"Select what SDR number\"), not command content - so only the address byte is "
        "translated, prepended to the rest of the frame left as real bytes.",
        _run_addr_token_plus_real_2arg,
    ),
    SendAttempt(
        "stripped_framing_raw_2arg",
        "NEW: maybe HEAD (7E7E) and STOP (0A0D) are added internally by the DLL and shouldn't be "
        "in what we pass - sends just type+addr+buf_len+payload, raw bytes.",
        _run_stripped_framing_raw_2arg,
    ),
    SendAttempt(
        "stripped_framing_hex_2arg",
        "NEW: same framing-stripped content as above, but hex-encoded - combining both open "
        "theories (framing and null-byte-safety) in one attempt.",
        _run_stripped_framing_hex_2arg,
    ),
    SendAttempt(
        "3arg_matching_commandtokens_shape",
        "NEW: SendCommandToSDR's argument count was never confirmed the way AutoConnectSDR's "
        "was - maybe it actually matches CommandTokens' OWN 3-arg shape (command, outBuffer, "
        "length), and any response comes back through that output buffer.",
        _run_3arg_matching_commandtokens_shape,
    ),
    SendAttempt(
        "addr_as_separate_int_arg",
        "NEW: maybe the address isn't part of the command string at all - a separate (long "
        "address, char* command, long length) signature, content = frame with the addr byte "
        "removed (HEAD/type/buf_len/payload/STOP intact). CONFIRMED CRASHING on real hardware "
        "(access violation reading 0x...05 - the DLL dereferenced our literal address int as a "
        "pointer) - real negative evidence, not a wasted attempt: whatever this parameter "
        "actually is, it isn't a plain c_long in this slot. ctypes/ Python catches this safely "
        "(see SendAttempt's docstring), it just always reports this exact crash, not -2.",
        _run_addr_as_separate_int_arg,
    ),
    SendAttempt(
        "addr_as_separate_string_arg",
        "Follow-up to addr_as_separate_int_arg's crash above: same idea (address as its own "
        "parameter, not embedded in the command), but as a real string pointer (b\"5\") instead "
        "of a raw int - all-pointer args like CommandTokens' own confirmed-safe 3-arg shape, to "
        "test the same theory without repeating that crash.",
        _run_addr_as_separate_string_arg,
    ),
]


def run_send_attempts(addr: int = 5):
    """Runs every SEND_ATTEMPTS candidate in turn against a REAL,
    well-formed, read-only Status Query for `addr` (a real channel,
    not 0 - the whiteboard's SDR module diagram labels modules SDR1
    through SDR16, no SDR0) and prints a side-by-side summary at the
    end. Status Query is read-only - it asks the module for its
    current state, it changes nothing - so this is the safest real
    command to probe with, even against real hardware, no matter which
    signature/content guess turns out to be closest.

    A run_fn raising is caught per-attempt (see SendAttempt/_try_send)
    so one bad signature guess (wrong ctypes arg types for real
    hardware to reject at the Python/ctypes boundary, not the DLL's
    own boundary) can't take down every other candidate in the same
    run. Extending this with a new theory later is one new
    SendAttempt(...) entry in SEND_ATTEMPTS above, not a new
    hand-written function + a new __main__ wiring step."""
    results = []
    for attempt in SEND_ATTEMPTS:
        print(f"\n  {attempt.label}: {attempt.reasoning}")
        outcome = attempt.run(addr)
        if outcome["error"] is not None:
            print(f"    -> ctypes call itself failed: {outcome['error']}")
        else:
            print(f"    -> return={outcome['return_code']}")
        results.append((attempt.label, outcome))

    print("\n  --- Summary ---")
    for label, outcome in results:
        shown = outcome["error"] if outcome["error"] is not None else f"return={outcome['return_code']}"
        print(f"    {label}: {shown}")
    return results


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
            f"\nStep 4: probe SendCommandToSDR with {len(SEND_ATTEMPTS)} different "
            "signature/content theories, all against the same REAL, well-formed, "
            "read-only Status Query - see run_send_attempts()'s docstring, and each "
            "SendAttempt's own reasoning in SEND_ATTEMPTS above, for what's being "
            "tried and why."
        )
        answer = input(
            "Send real Status Query probes to the connected hardware now? [y/N] "
        ).strip().lower()
        if answer == "y":
            run_send_attempts()
            print("\nStep 4b: check status again - compare this buffer to Step 2's by eye")
            test_check_connection()
        else:
            print("Skipped - no real command sent.")

    print("\nStep 5: disconnect")
    test_disconnect()
