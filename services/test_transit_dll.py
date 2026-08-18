import ctypes
import os
import sys

if not sys.platform.startswith("win"):
    sys.exit("This only runs on Windows - Transit.dll is a native Windows DLL.")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.protocol.commands import query_status, set_signal
from services.protocol import constants as c
from services.team_vocab import (
    HEAD_TOKEN, STOP_TOKEN, TYPE_TOKENS, OUTPUT_TOKENS, MODE_TOKENS,
    BANDWIDTH_TOKENS, RESP_TOKENS, LEVEL_TOKENS,
)
from state.level_map import LEVEL_TO_HEX

DLL_PATH = "dll/Transit.dll"

dll = ctypes.WinDLL(DLL_PATH)

dll.AutoConnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.AutoConnectSDR.restype = ctypes.c_long

dll.CheckConnection.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.CheckConnection.restype = ctypes.c_long

dll.DisconnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
dll.DisconnectSDR.restype = ctypes.c_long

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
    out = ctypes.create_string_buffer(256)
    result = dll.CommandTokens(token, out, ctypes.sizeof(out))
    print(f"CommandTokens({token!r}) -> return={result}, buffer={out.value!r}")
    return result


def test_command_tokens_team_vocab():
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
    result = dll.SendCommandToSDR(command, len(command))
    print(f"SendCommandToSDR({command!r}) -> return={result}")
    return result


def translate_frame_via_dll(frame: bytes) -> str:
    tokens = []
    for byte in frame:
        out = ctypes.create_string_buffer(256)
        dll.CommandTokens(bytes([byte]).hex().upper().encode(), out, ctypes.sizeof(out))
        tokens.append(out.value.decode('ascii', errors='replace'))
    return "".join(tokens)


def send_frame_one_token_at_a_time(frame: bytes):
    print(f"Sending frame {frame.hex(' ').upper()} as one bare token per byte:")
    dll.SendCommandToSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
    dll.SendCommandToSDR.restype = ctypes.c_long
    results = []
    for byte in frame:
        out = ctypes.create_string_buffer(256)
        dll.CommandTokens(bytes([byte]).hex().upper().encode(), out, ctypes.sizeof(out))
        token = out.value
        fallback = False
        if token == b"??":
            token = bytes([byte]).hex().upper().encode()
            fallback = True
        result = dll.SendCommandToSDR(token, len(token))
        note = " (hex-text fallback, no alias)" if fallback else ""
        print(f"  byte 0x{byte:02X} -> token {token!r}{note} -> SendCommandToSDR return={result}")
        results.append((byte, token, result))
    return results


def test_send_one_token_at_a_time(addr: int = 5):
    return send_frame_one_token_at_a_time(query_status(addr))


def test_send_signal_control_one_token_at_a_time(addr: int = 5):
    frame = set_signal(addr, c.BLIND_DEFAULT_MODE, c.BLIND_DEFAULT_FREQ_MHZ, c.BLIND_DEFAULT_BANDWIDTH_MHZ, LEVEL_TO_HEX[1])
    return send_frame_one_token_at_a_time(frame)


class SendAttempt:

    def __init__(self, label: str, reasoning: str, run):
        self.label = label
        self.reasoning = reasoning
        self.run = run


def _try_send(argtypes, restype, args) -> dict:
    dll.SendCommandToSDR.argtypes = argtypes
    dll.SendCommandToSDR.restype = restype
    try:
        result = dll.SendCommandToSDR(*args)
        return {"return_code": result, "error": None}
    except Exception as e:
        return {"return_code": None, "error": str(e)}


def _addr_token(addr_byte: bytes) -> str:
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
    token = _addr_token(frame[3:4])
    content = token.encode() + frame[:3] + frame[4:]
    return _try_send([ctypes.c_char_p, ctypes.c_long], ctypes.c_long, (content, len(content)))


def _run_stripped_framing_raw_2arg(addr: int) -> dict:
    content = query_status(addr)[2:-2]
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
    content = frame[:3] + frame[4:]
    return _try_send(
        [ctypes.c_long, ctypes.c_char_p, ctypes.c_long], ctypes.c_long,
        (addr, content, len(content)),
    )


def _run_addr_as_separate_string_arg(addr: int) -> dict:
    frame = query_status(addr)
    addr_str = str(addr).encode()
    content = frame[:3] + frame[4:]
    return _try_send(
        [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long], ctypes.c_long,
        (addr_str, content, len(content)),
    )


REPEAT_COUNT = 4

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

    BASELINE_CODES = {-2}
    outcomes_by_label = dict(results)
    interesting_labels = [
        label for label, outcome in results
        if outcome["error"] is None and outcome["return_code"] not in BASELINE_CODES
    ]
    if interesting_labels:
        print("\n  --- Reproducibility check on non-(-2) result(s) ---")
        attempts_by_label = {a.label: a for a in SEND_ATTEMPTS}
        for label in interesting_labels:
            attempt = attempts_by_label[label]
            first_code = outcomes_by_label[label]["return_code"]
            repeat_codes = []
            for _ in range(REPEAT_COUNT):
                outcome = attempt.run(addr)
                repeat_codes.append(outcome["error"] if outcome["error"] is not None else outcome["return_code"])
            consistent = repeat_codes == [first_code] * REPEAT_COUNT
            print(f"    {label}: first={first_code}, {REPEAT_COUNT} more attempts -> {repeat_codes}")
            print(f"    {'CONSISTENT - worth trusting' if consistent else 'INCONSISTENT - may have been a fluke, do not trust yet'}")

    return results


if __name__ == "__main__":
    print(f"Loaded {DLL_PATH} OK\n")
    print("Step 1: connect")
    connect_result = test_auto_connect()
    print("\nStep 2: check status")
    test_check_connection()

    print("\nStep 2b: probe CommandTokens with the real FME/NOX/etc team vocabulary")
    test_command_tokens_team_vocab()

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
            print(
                "\nStep 4a: one bare token per byte, Status Query (read-only) - "
                "see send_frame_one_token_at_a_time()'s docstring"
            )
            test_send_one_token_at_a_time()

            print(
                "\nStep 4b: one bare token per byte, Signal Control (ACTUATING - "
                "this changes real RF output configuration, not read-only like "
                "Status Query above) - CONFIRMED reaching real hardware, see "
                "test_send_signal_control_one_token_at_a_time()'s docstring"
            )
            signal_answer = input(
                "This sends a real Signal Control command (mode/freq/bandwidth/"
                "power) - continue? [y/N] "
            ).strip().lower()
            if signal_answer == "y":
                test_send_signal_control_one_token_at_a_time()
            else:
                print("Skipped.")

            print("\nStep 4c: the 9-theory battery from before, for comparison")
            run_send_attempts()
            print("\nStep 4d: check status again - compare this buffer to Step 2's by eye")
            test_check_connection()
        else:
            print("Skipped - no real command sent.")

    print("\nStep 5: disconnect")
    test_disconnect()
