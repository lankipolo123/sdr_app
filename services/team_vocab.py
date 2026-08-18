"""Encodes an outgoing command frame into the team's own 3-letter token
vocabulary - the scheme from the whiteboard/senior, not anything found
by disassembling Transit.dll. Pure Python, no DLL involved: every
mapping below is a fixed table the team defined themselves, so this
works identically on any platform and never fails or falls back.

Only fields that actually HAVE a defined token get one. Two real
protocol fields - the channel address, and Signal Control's frequency
(an arbitrary 300-6000 MHz integer, not one of a small fixed set) -
have no token defined anywhere in the team's vocabulary. Rather than
invent codes for those (which would be exactly the made-up-value
problem this whole effort is trying to avoid), they're shown plainly
in brackets, e.g. "[addr=5]" - a visible gap to fill in once the team
defines one, not a silent guess standing in for it.
"""
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

# L0 deliberately reuses OUTPUT_OFF's own token (XXX) - matches the
# team's own notes ("L0 = XXX, matches OUTPUT_OFF - intentional"), not
# a collision introduced here.
LEVEL_TOKENS = {
    0: "XXX",
    1: "L1X",
    2: "L2X",
    3: "L3X",
}


def encode_team_tokens(frame: bytes) -> str:
    """Translates one outgoing TX frame (as built by services/protocol/
    packet_builder.py) into the team's token vocabulary, space-
    separated, in wire order: HEAD, TYPE, ADDR, <payload tokens>, STOP.
    Never raises and never returns None - every field either has a
    real token or an explicit bracketed placeholder, so there's always
    something to show."""
    if len(frame) < 5:
        return "[malformed frame]"

    type_byte = frame[2]
    addr = frame[3]
    buf_len = frame[4]
    buf = frame[5:5 + buf_len]

    tokens = [HEAD_TOKEN]
    tokens.append(TYPE_TOKENS.get(type_byte, f"[type=0x{type_byte:02X}]"))
    # No team-defined token for the address itself yet - see module
    # docstring.
    tokens.append(f"[addr={addr}]")

    if type_byte == c.TYPE_OUTPUT_SWITCH and len(buf) == 1:
        tokens.append(OUTPUT_TOKENS.get(buf[0], f"[out=0x{buf[0]:02X}]"))

    elif type_byte == c.TYPE_SIGNAL_CONTROL and len(buf) == 5:
        mode, bw_code, power_code = buf[0], buf[3], buf[4]
        freq = struct.unpack(">H", buf[1:3])[0]
        tokens.append(MODE_TOKENS.get(mode, f"[mode=0x{mode:02X}]"))
        # No team-defined token for an arbitrary frequency value - see
        # module docstring.
        tokens.append(f"[freq={freq}MHz]")
        bw_mhz = c.BANDWIDTH_CODES_REV.get(bw_code)
        bw_token = BANDWIDTH_TOKENS.get(bw_mhz) if bw_mhz is not None else None
        tokens.append(bw_token if bw_token else f"[bw=0x{bw_code:02X}]")
        level = HEX_TO_LEVEL.get(power_code)
        level_token = LEVEL_TOKENS.get(level) if level is not None else None
        tokens.append(level_token if level_token else f"[power=0x{power_code:02X}]")

    elif type_byte == c.TYPE_STATUS_QUERY:
        pass  # no payload

    else:
        tokens.append(f"[payload={buf.hex(' ').upper()}]")

    tokens.append(STOP_TOKEN)
    return " ".join(tokens)
