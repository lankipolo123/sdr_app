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
        _dll = dll
    except OSError as e:
        _dll_load_error = str(e)
    return _dll


def dll_command_tokens(data: bytes) -> tuple[str | None, str | None]:
    """Calls the real Transit.dll CommandTokens export on data (the
    raw TX frame bytes). Returns (value, None) on success, or
    (None, reason) on any failure - DLL not loadable, wrong platform,
    or the call itself raising. This is what the main Logs panel's TX
    line and dev mode's "ENC:" preview both show now, in place of the
    old Python-side AES-256-GCM demo (encode_message() above this
    section is unchanged and still usable, just no longer called from
    here).

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
