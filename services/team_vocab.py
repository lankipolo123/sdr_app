import struct

from services.protocol import constants as c
from state.level_map import HEX_TO_LEVEL

HEAD_TOKEN = "FME"
STOP_TOKEN = "STP"

TYPE_TOKENS = {
    c.TYPE_OUTPUT_SWITCH: "NOX",
    c.TYPE_SIGNAL_CONTROL: "NTX",
    c.TYPE_STATUS_QUERY: "FMQ",
}

OUTPUT_TOKENS = {
    c.OUTPUT_OFF: "XXX",
    c.OUTPUT_ON: "YXX",
}

MODE_TOKENS = {
    c.MODE_WHITE_NOISE: "MXX",
    c.MODE_LINEAR_SWEEP: "MOX",
    c.MODE_COMB_SPECTRUM: "MTX",
    c.MODE_SINGLE: "MRX",
}

BANDWIDTH_TOKENS = {
    10: "HTZ", 20: "BFM", 50: "HFZ", 100: "BSM",
    150: "HNZ", 200: "BCM", 250: "HEZ", 300: "BEM",
}

RESP_TOKENS = {
    c.RESP_FAILED: "XF",
    c.RESP_SUCCESS: "SS",
}

LEVEL_TOKENS = {
    0: "XXX",
    1: "L1X",
    2: "L2X",
    3: "L3X",
}


def encode_team_tokens(frame: bytes) -> str:
    if len(frame) < 5:
        return "[malformed frame]"

    type_byte = frame[2]
    addr = frame[3]
    buf_len = frame[4]
    buf = frame[5:5 + buf_len]

    tokens = [HEAD_TOKEN]
    tokens.append(TYPE_TOKENS.get(type_byte, f"[type=0x{type_byte:02X}]"))
    tokens.append(f"[addr={addr}]")

    if type_byte == c.TYPE_OUTPUT_SWITCH and len(buf) == 1:
        tokens.append(OUTPUT_TOKENS.get(buf[0], f"[out=0x{buf[0]:02X}]"))

    elif type_byte == c.TYPE_SIGNAL_CONTROL and len(buf) == 5:
        mode, bw_code, power_code = buf[0], buf[3], buf[4]
        freq = struct.unpack(">H", buf[1:3])[0]
        tokens.append(MODE_TOKENS.get(mode, f"[mode=0x{mode:02X}]"))
        tokens.append(f"[freq={freq}MHz]")
        bw_mhz = c.BANDWIDTH_CODES_REV.get(bw_code)
        bw_token = BANDWIDTH_TOKENS.get(bw_mhz) if bw_mhz is not None else None
        tokens.append(bw_token if bw_token else f"[bw=0x{bw_code:02X}]")
        level = HEX_TO_LEVEL.get(power_code)
        level_token = LEVEL_TOKENS.get(level) if level is not None else None
        tokens.append(level_token if level_token else f"[power=0x{power_code:02X}]")

    elif type_byte == c.TYPE_STATUS_QUERY:
        pass

    else:
        tokens.append(f"[payload={buf.hex(' ').upper()}]")

    tokens.append(STOP_TOKEN)
    return " ".join(tokens)
