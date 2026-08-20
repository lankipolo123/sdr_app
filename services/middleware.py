import ctypes
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from services.protocol import constants as c
from state.level_map import LEVEL_TO_HEX

if TYPE_CHECKING:
    from hooks.use_channel import ChannelController

MAX_CHANNELS = 16


class Action(Enum):
    OUTPUT_ON = "output_on"
    OUTPUT_OFF = "output_off"
    SET_LEVEL = "set_level"
    SET_MODE = "set_mode"


class InvalidToken(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    channel: int
    action: Action
    level: int | None = None
    mode: int | None = None


def validate_token(token: Token) -> None:
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
    validate_token(token)

    if token.action is Action.OUTPUT_ON:
        controller.turn_output_on()
    elif token.action is Action.OUTPUT_OFF:
        controller.turn_output_off()
    elif token.action is Action.SET_LEVEL:
        power_code = LEVEL_TO_HEX[token.level]
        if power_code is None:
            controller.turn_output_off()
        else:
            controller.set_power(power_code)
    elif token.action is Action.SET_MODE:
        controller.set_mode(token.mode)
    else:
        raise InvalidToken(f"no dispatch implemented for action={token.action}")


if getattr(sys, "frozen", False):
    _DLL_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "dll", "Transit.dll")
else:
    _DLL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dll", "Transit.dll")

_dll = None
_dll_load_error = None


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
        dll.AutoConnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
        dll.AutoConnectSDR.restype = ctypes.c_long
        dll.CheckConnection.argtypes = [ctypes.c_char_p, ctypes.c_long]
        dll.CheckConnection.restype = ctypes.c_long
        dll.DisconnectSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
        dll.DisconnectSDR.restype = ctypes.c_long
        dll.SendCommandToSDR.argtypes = [ctypes.c_char_p, ctypes.c_long]
        dll.SendCommandToSDR.restype = ctypes.c_long
        _dll = dll
    except OSError as e:
        _dll_load_error = str(e)
    return _dll


def dll_auto_connect() -> tuple[int | None, str | None, str | None]:
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
            token = out.value
            if token == b"??":
                token = bytes([byte]).hex().upper().encode()
            result = dll.SendCommandToSDR(token, len(token))
        return result, None
    except Exception as e:
        return None, str(e)


def dll_command_tokens(data: bytes) -> tuple[str | None, str | None]:
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
    if _get_dll() is None:
        return None, _dll_load_error
    tokens = []
    for byte in frame:
        value, error = dll_command_tokens(bytes([byte]))
        if value is None:
            return None, error
        text = decode_dll_text(value)
        if text == "??":
            text = bytes([byte]).hex().upper()
        tokens.append(text)
    return " ".join(tokens), None


def dll_log_text(data: bytes) -> str:
    value, error = dll_decode_frame(data)
    return value if value is not None else f"[middleware unavailable: {error}]"


def decode_dll_text(hex_value: str) -> str:
    try:
        raw = bytes.fromhex(hex_value.replace(' ', ''))
        text = raw.decode('ascii')
    except (ValueError, UnicodeDecodeError):
        return hex_value
    return text if text.isprintable() else hex_value
