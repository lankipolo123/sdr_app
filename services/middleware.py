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

This is a sketch for review, not wired into the running app - nothing
here is imported by main.py/app.py/pages/. If it's adopted, dispatch_token()
would sit in front of ChannelController (hooks/use_channel.py), reusing
its existing connect/retry/send logic rather than reimplementing it -
Transit.dll's "auto connect / check status / disconnect / send to SDR"
functions map directly onto ConnectionController and ChannelController,
which already do exactly that.
"""
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
