"""Sketch of the "Transit.dll" middleware boundary described on the
whiteboard: GUI -> Token -> Middleware -> real SDR command.

The whole point of this layer is that a Token CANNOT express an unsafe
value - there is no field for raw hex, a custom frequency, or a raw
power byte. A caller (an external GUI, or a DLL FFI boundary where
Python's own type system can't be trusted to have been respected on
the other side) can only ever say "channel N, do X" where X is one of
a small fixed set of actions - never "send these exact bytes."
validate_token() re-checks every field defensively as if it arrived as
plain untyped ints, because across a real FFI/DLL boundary that's
exactly what it would be.

The Token/validate_token/dispatch_token pipeline below is still a
sketch for review, not wired into the running app - ChannelManager.
send_token() (hooks/use_channels.py) can call it, but nothing in the
GUI calls send_token() yet; ChannelCard still calls ChannelController's
methods directly. If adopted, dispatch_token() would sit in front of
ChannelController (hooks/use_channel.py), reusing its existing
connect/retry/send logic rather than reimplementing it - Transit.dll's
"auto connect / check status / disconnect / send to SDR" functions map
directly onto ConnectionController and ChannelController, which already
do exactly that.

dll_command_tokens() at the bottom of this file IS wired into the
running app (pages/main_page.py's dev-mode preview) - it's a separate,
much smaller thing: a direct ctypes call into Transit.dll's real
CommandTokens export, Windows-only, fails soft (never raises) so a
missing/absent DLL can't take the GUI down.
"""
import ctypes
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from services.protocol import constants as c
from state.level_map import LEVEL_TO_HEX

if TYPE_CHECKING:
    # Only needed for the type hint on dispatch_token() below, never
    # at runtime - importing this for real would create a circular
    # import: hooks/__init__.py eagerly imports use_app -> use_channels
    # -> (now) this module, so this module importing hooks.use_channel
    # back would loop into a package that's still mid-load.
    from hooks.use_channel import ChannelController

MAX_CHANNELS = 16  # matches hooks/use_channels.py - keep these in sync


class Action(Enum):
    OUTPUT_ON = "output_on"
    OUTPUT_OFF = "output_off"
    SET_LEVEL = "set_level"
    SET_MODE = "set_mode"


class InvalidToken(ValueError):
    """Raised by validate_token() - the caller sent something that
    doesn't correspond to a real, safe command. Never silently
    clamped/ignored: a malformed Token means the caller (or whatever
    modified the Token in transit) is doing something unexpected, and
    that's worth surfacing loudly rather than guessing at intent."""


@dataclass(frozen=True)
class Token:
    """The ONLY thing that crosses the GUI -> Middleware boundary.
    channel is 1-16 (the CH number shown on screen, matching
    ChannelState.display_number - not the internal 0-based address).
    level/mode are only used by their matching action; irrelevant for
    OUTPUT_ON/OFF, which take no parameters at all."""
    channel: int
    action: Action
    level: int | None = None   # required for SET_LEVEL - must be 0-3
    mode: int | None = None    # required for SET_MODE - must be a key in constants.MODE_NAMES


def validate_token(token: Token) -> None:
    """The actual safety gate. Everything here is deliberately
    defensive - treats every field as if it arrived as a raw,
    untrusted int from outside Python's own type system (e.g. across
    a DLL's C ABI), not as a Token guaranteed to already be well-formed
    just because its type annotations say so."""
    if not isinstance(token.channel, int) or not (1 <= token.channel <= MAX_CHANNELS):
        raise InvalidToken(f"channel must be an int 1-{MAX_CHANNELS}, got {token.channel!r}")

    if not isinstance(token.action, Action):
        raise InvalidToken(f"action must be a real Action, got {token.action!r}")

    if token.action is Action.SET_LEVEL:
        if not isinstance(token.level, int) or token.level not in LEVEL_TO_HEX:
            raise InvalidToken(f"level must be one of {sorted(LEVEL_TO_HEX)}, got {token.level!r}")
    elif token.level is not None:
        raise InvalidToken(f"level is only valid with SET_LEVEL, got action={token.action}")

    if token.action is Action.SET_MODE:
        if not isinstance(token.mode, int) or token.mode not in c.MODE_NAMES:
            raise InvalidToken(f"mode must be one of {sorted(c.MODE_NAMES)}, got {token.mode!r}")
    elif token.mode is not None:
        raise InvalidToken(f"mode is only valid with SET_MODE, got action={token.action}")


def dispatch_token(controller: "ChannelController", token: Token) -> None:
    """Translate + send: validates first, then calls the one matching
    ChannelController method for real. controller must already be the
    ChannelController for token.channel - picking the right controller
    for a channel number is ChannelManager's job (hooks/use_channels.py),
    not this layer's.

    Note what ISN'T here: no path from a Token to commands.set_signal()
    or raw frame bytes directly. Every action bottoms out in one of
    ChannelController's existing public methods, which are themselves
    already limited to safe, table-driven values - this layer is an
    extra gate in front of that, not a new way to reach the wire."""
    validate_token(token)

    if token.action is Action.OUTPUT_ON:
        controller.turn_output_on()
    elif token.action is Action.OUTPUT_OFF:
        controller.turn_output_off()
    elif token.action is Action.SET_LEVEL:
        power_code = LEVEL_TO_HEX[token.level]
        if power_code is None:  # L0 = off, never a real Signal Control value
            controller.turn_output_off()
        else:
            controller.set_power(power_code)
    elif token.action is Action.SET_MODE:
        controller.set_mode(token.mode)
    else:
        # Unreachable if validate_token() ran first, but no silent
        # fallback - an Action with no dispatch branch is a bug in
        # THIS file, not something to swallow.
        raise InvalidToken(f"no dispatch implemented for action={token.action}")


# ---- Real Transit.dll call (dev-mode preview only) ----

# Same "dll/Transit.dll" relative path as services/test_transit_dll.py,
# but resolved from THIS file's location rather than the current
# working directory - main.py can be launched from anywhere, unlike
# the standalone test script which assumes it's run from the repo root.
#
# sys.frozen is set by PyInstaller (and other freezers) on the packaged
# .exe, never when running from source - __file__-based resolution
# would silently break under a onefile build, since PyInstaller
# extracts everything to a temporary directory at runtime and __file__
# points there, not to wherever the real installed .exe (and the real
# dll/Transit.dll shipped next to it - see installer.iss) actually
# lives on disk. sys.executable is the real .exe's own path in that
# case, so dll/Transit.dll needs to be found relative to THAT instead.
if getattr(sys, "frozen", False):
    _DLL_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "dll", "Transit.dll")
else:
    _DLL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dll", "Transit.dll")

_dll = None          # cached handle once successfully loaded
_dll_load_error = None  # cached failure reason, so a missing DLL doesn't retry on every call


def _get_dll():
    global _dll, _dll_load_error
    if _dll is not None or _dll_load_error is not None:
        return _dll
    try:
        if not hasattr(ctypes, "WinDLL"):
            raise OSError("Transit.dll is a Windows DLL - ctypes.WinDLL doesn't exist on this platform")
        dll = ctypes.WinDLL(_DLL_PATH)
        dll.CommandTokens.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long]
        dll.CommandTokens.restype = ctypes.c_long
        # AutoConnectSDR's shape is CONFIRMED (real VB6 Declare
        # statement, and observed working against real hardware -
        # return=4, buffer=b'Connected' - see services/test_transit_dll.py).
        # CheckConnection/DisconnectSDR are declared the same (char*
        # buffer, long length) -> long shape by symmetry, NOT
        # independently confirmed the same way.
        dll.AutoConnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
        dll.AutoConnectSDR.restype = ctypes.c_long
        dll.CheckConnection.argtypes = [ctypes.c_char_p, ctypes.c_long]
        dll.CheckConnection.restype = ctypes.c_long
        dll.DisconnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
        dll.DisconnectSDR.restype = ctypes.c_long
        # SendCommandToSDR's real (char* command, long length) shape -
        # dll_send_command() below re-declares this itself right before
        # calling anyway (ctypes allows that freely), so this default
        # is mostly documentation: see that function's docstring for
        # why one-bare-token-per-call is the strongest theory found so
        # far, from disassembling the real 32-bit Transit.dll.
        dll.SendCommandToSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
        dll.SendCommandToSDR.restype = ctypes.c_long
        _dll = dll
    except OSError as e:
        _dll_load_error = str(e)
    return _dll


def dll_auto_connect() -> tuple[int | None, str | None, str | None]:
    """Calls the real Transit.dll AutoConnectSDR export - CONFIRMED
    working (return=4, buffer=b'Connected' with real hardware attached;
    return=-1, buffer=b'DisConnected' with nothing attached - see
    services/test_transit_dll.py). No port name, baud, parity, or data
    bits is passed - AutoConnectSDR owns port discovery entirely
    internally, unlike the pyserial-based SerialManager.open() this
    replaces (hooks/use_connection.py).

    Returns (return_code, buffer_text, None) on a completed call, or
    (None, None, reason) if the DLL itself couldn't be reached (missing
    file, wrong platform, call raised) - same never-raises guarantee as
    dll_command_tokens() below."""
    dll = _get_dll()
    if dll is None:
        return None, None, _dll_load_error
    try:
        buf = ctypes.create_string_buffer(256)
        result = dll.AutoConnectSDR(buf, ctypes.sizeof(buf))
        return result, buf.value.decode("ascii", errors="replace"), None
    except Exception as e:
        return None, None, str(e)


def dll_check_connection() -> tuple[int | None, str | None, str | None]:
    """Same shape as dll_auto_connect(), for CheckConnection - confirmed
    callable and returns a sensible buffer (return=40, buffer=b'Connected'
    observed with real hardware attached), though its return-code
    convention (is 40 always "connected"? what does "not connected"
    look like from THIS function specifically?) isn't independently
    confirmed the way AutoConnectSDR's -1/4 is."""
    dll = _get_dll()
    if dll is None:
        return None, None, _dll_load_error
    try:
        buf = ctypes.create_string_buffer(256)
        result = dll.CheckConnection(buf, ctypes.sizeof(buf))
        return result, buf.value.decode("ascii", errors="replace"), None
    except Exception as e:
        return None, None, str(e)


def dll_disconnect() -> tuple[int | None, str | None, str | None]:
    """Same shape again, for DisconnectSDR - observed return=1,
    buffer=b'' against real hardware (services/test_transit_dll.py)."""
    dll = _get_dll()
    if dll is None:
        return None, None, _dll_load_error
    try:
        buf = ctypes.create_string_buffer(256)
        result = dll.DisconnectSDR(buf, ctypes.sizeof(buf))
        return result, buf.value.decode("ascii", errors="replace"), None
    except Exception as e:
        return None, None, str(e)


def dll_send_command(data: bytes) -> tuple[int | None, str | None]:
    """Sends `data` (a real frame built by packet_builder.py) as one
    BARE TOKEN PER BYTE, not as one call carrying the whole frame -
    CONFIRMED as the strongest shape found so far by disassembling the
    REAL working 32-bit Transit.dll (pulled from an actual installed
    "Noise Controller" app, not this repo's dll/Transit.dll - see the
    conversation): SendCommandToSDR itself builds the exact same
    22-entry token table CommandTokens uses (X#0->00, X#A->01, ...,
    X#P->10, XME->7E, XOP->FF, X#X/XHT/XGY->D0-D2), read directly out
    of its own disassembled code - meaning it validates its input
    against these same short tokens, not against raw frame bytes or a
    whole translated string. Every byte of a real Status Query frame
    sent this way (7 calls) returned 1 on real hardware - every
    single one, not just one lucky call, which is stronger evidence
    than the previous address-as-separate-parameter shape (also
    returned 1, but only proved the DLL accepted the CALL, not that a
    module actually reacted to it - see services/test_transit_dll.py's
    test_send_one_token_at_a_time()).

    This confirms the DLL ACCEPTS the calls - it does NOT yet confirm
    real hardware receives or acts on them. There is still no
    confirmed way to read a response back through the DLL, so whether
    a module actually reacts still needs a physical check (spectrum
    analyzer, an LED, anything external) on an actuating command like
    Output ON - not something this function alone can confirm.

    Returns (return_code, None) on a completed sequence - the LAST
    byte's return_code (the STOP byte's), representative of the whole
    sequence since every byte returned identically in the one real
    test run so far, not a guarantee every byte always will - or
    (None, reason) the moment the DLL itself can't be reached, or a
    call for one byte fails outright (not just returns a non-1 code -
    an actual raised exception), without sending the remaining bytes
    of a frame that's already partway wrong."""
    dll = _get_dll()
    if dll is None:
        return None, _dll_load_error
    dll.SendCommandToSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
    dll.SendCommandToSDR.restype = ctypes.c_long
    dll.CommandTokens.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_long]
    dll.CommandTokens.restype = ctypes.c_long
    result = None
    try:
        for byte in data:
            out = ctypes.create_string_buffer(256)
            dll.CommandTokens(bytes([byte]).hex().upper().encode(), out, ctypes.sizeof(out))
            token = out.value  # e.g. b"X#E" - CommandTokens' own confirmed output, used as-is
            if token == b"??":
                # No token exists for this byte - true for most bytes of
                # a Signal Control frame's frequency field (a real
                # 300-6000 MHz value, not a small enum like mode/
                # bandwidth/power, which DO all fall inside the
                # confirmed 22-entry table). CONFIRMED by disassembling
                # SendCommandToSDR itself (not just CommandTokens): it
                # uppercases its input, hashes it, and looks it up in
                # this SAME 22-entry table first - if that misses, it
                # falls back to parsing the input STRING AS 2-DIGIT HEX
                # TEXT (radix 16, must fit 0-255) and uses that parsed
                # value. A raw binary byte (an earlier, wrong guess
                # here) isn't parseable hex text at all - the fallback
                # needs the hex DIGITS themselves, e.g. b"92" for 0x92,
                # not the single byte 0x92.
                token = bytes([byte]).hex().upper().encode()
            result = dll.SendCommandToSDR(token, len(token))
        return result, None
    except Exception as e:
        return None, str(e)


def dll_command_tokens(data: bytes) -> tuple[str | None, str | None]:
    """Calls the real Transit.dll CommandTokens export on data.
    Returns (value, None) on success, or (None, reason) on any failure
    - DLL not loadable, wrong platform, or the call itself raising.
    This is what the main Logs panel's TX line and dev mode's "ENC:"
    preview both show now, in place of the old Python-side AES-256-GCM
    demo (encode_message() above this section is unchanged and still
    usable, just no longer called from here).

    data should be a single byte matching one of CommandTokens' real
    lookup table keys (00-10, 7E, FF, D0-D2 - confirmed by
    disassembling Transit.dll and verified byte-by-byte in services/
    test_command_tokens.py). CommandTokens does one whole-input match
    against 2-hex-digit keys, not a per-byte scan across a longer
    string - a multi-byte frame passed as one hex string can never
    match any key and always falls back to "??". pages/main_page.py's
    _on_raw_tx passes just the channel address byte (0-16, one of the
    confirmed keys), not the whole TX frame.

    A tuple, not a single string with the error baked in as bracketed
    text - callers need to tell success from failure explicitly (the
    main Logs panel wants a short generic fallback on failure, dev
    mode wants the real reason), and string-sniffing a magic prefix to
    tell them apart is fragile compared to just returning both.

    CommandTokens' real expected input/output format is NOT fully
    confirmed, but static analysis of the DLL's own binary (reading
    the literal lookup table it builds at startup directly out of its
    .rdata section) found it maps specific byte values to 3-character
    codes using UPPERCASE two-hex-digit keys ("7E" -> "XME", "0A" ->
    "X#J", etc.) - so data is hex-encoded AND uppercased before being
    passed across. Lowercase hex (Python's default) would silently
    mismatch every key containing a letter (A-F), including the HEAD/
    STOP bytes present in literally every frame - a real, confirmed
    bug this fixes, not a guess. Hex-encoding at all (rather than
    sending raw binary) is still needed regardless, since raw binary
    could contain an embedded null byte and truncate a C string early.

    Returns the actual response bytes as hex, not decoded as UTF-8
    text - if CommandTokens is genuinely producing encrypted/binary
    output (plausible, since "translate tokens" is meant to be the
    encryption step), decoding it as text garbles into unreadable
    replacement-character noise instead of anything legible. Hex is
    always printable regardless of whether the real bytes are text,
    binary ciphertext, or anything else - this is the real DLL output,
    not a placeholder or a guess at what it means.

    Never raises: the main Logs panel and dev mode are both optional/
    cosmetic, so a missing DLL, a non-Windows platform, or an
    unexpected call failure must never be able to take the GUI down -
    they just come back as the error half of the tuple instead."""
    dll = _get_dll()
    if dll is None:
        return None, _dll_load_error
    try:
        out = ctypes.create_string_buffer(256)
        dll.CommandTokens(data.hex().upper().encode(), out, ctypes.sizeof(out))
        return out.value.hex(' ').upper(), None
    except Exception as e:
        return None, str(e)


def dll_decode_frame(frame: bytes) -> tuple[str | None, str | None]:
    """Decodes a WHOLE multi-byte command frame through the real DLL,
    not just the one address byte dll_command_tokens() is normally
    given. CommandTokens itself was never changed - it still only ever
    matches ONE whole input against its 2-hex-digit keys (confirmed by
    disassembly, see dll_command_tokens()'s docstring) - so this drives
    that same confirmed-working single-byte call once per byte in
    `frame`, in order, and joins the results. That's the only way to
    get full-frame coverage out of a function that can't take more
    than one byte per call; it is not a guess at some different,
    unconfirmed CommandTokens behavior.

    A byte with no table entry (anything outside 00-10, 7E, FF,
    D0-D2 - e.g. most bytes of an arbitrary frequency value) still
    gets a real answer from the DLL, its documented "??"
    (unrecognized) response - dropped from the joined output rather
    than shown, purely for display noise (one less recognizable field
    isn't information the DLL wasn't already going to omit - "??"
    carries no more meaning than a gap does). Every byte is still sent
    to the DLL for real; this only affects which of the real responses
    make it into the joined string.

    Returns (joined_text, None) on success, or (None, reason) the
    moment the DLL itself is unreachable (not loaded/wrong platform) -
    same failure shape as dll_command_tokens(), so callers handle it
    identically. A mid-frame call failure (as opposed to a routine "??"
    match-miss) also short-circuits this way rather than returning a
    partial join, since a broken call partway through means the DLL
    connection itself failed, not that the remaining bytes are safe to
    skip."""
    if _get_dll() is None:
        return None, _dll_load_error
    tokens = []
    for byte in frame:
        value, error = dll_command_tokens(bytes([byte]))
        if value is None:
            return None, error
        text = decode_dll_text(value)
        if text != "??":
            tokens.append(text)
    return " ".join(tokens), None


def dll_log_text(data: bytes) -> str:
    """Convenience wrapper around dll_decode_frame() for plain log
    lines (ChannelController, ChannelManager's _QueryAttempt, etc.)
    that just want one hex-free string to write to the log - those call sites don't need
    to distinguish failure reasons the way the GUI's dev-mode display
    does, just something other than raw hex to put in the line.
    Never raises, same guarantee as dll_decode_frame() itself."""
    value, error = dll_decode_frame(data)
    return value if value is not None else f"[middleware unavailable: {error}]"


def decode_dll_text(hex_value: str) -> str:
    """Turns dll_command_tokens()'s hex string back into the actual
    token text - "58 23 50" -> "X#P" - since every response CommandTokens
    has actually been confirmed to return (every table entry checked in
    services/test_command_tokens.py) IS plain printable text, not
    binary/ciphertext. Hex is still what dll_command_tokens() itself
    returns (see its docstring - kept in case a future response really
    isn't text), this is just the display-layer step that turns it into
    the literal word on screen.

    Falls back to the original hex string, never raises or shows
    replacement-character noise, if a response ever isn't clean
    printable ASCII - that would mean something unexpected came back,
    not that the raw hex is unsafe to show."""
    try:
        raw = bytes.fromhex(hex_value.replace(' ', ''))
        text = raw.decode('ascii')
    except (ValueError, UnicodeDecodeError):
        return hex_value
    return text if text.isprintable() else hex_value
