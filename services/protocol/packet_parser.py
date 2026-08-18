import struct
from dataclasses import dataclass

from . import constants as c
from state.level_map import HEX_TO_LEVEL, LEVEL_LABELS


def describe_command(frame: bytes) -> str:
    if len(frame) < 5:
        return "malformed frame"
    type_byte = frame[2]
    buf_len = frame[4]
    buf = frame[5:5 + buf_len]

    if type_byte == c.TYPE_OUTPUT_SWITCH and len(buf) == 1:
        return f"Output Switch: {'ON' if buf[0] == c.OUTPUT_ON else 'OFF'}"

    if type_byte == c.TYPE_SIGNAL_CONTROL and len(buf) == 5:
        mode, bw_code, power_code = buf[0], buf[3], buf[4]
        freq = struct.unpack(">H", buf[1:3])[0]
        mode_name = c.MODE_NAMES.get(mode, f"0x{mode:02X}")
        bandwidth = c.BANDWIDTH_CODES_REV.get(bw_code)
        bw_str = f"{bandwidth}MHz" if bandwidth is not None else f"0x{bw_code:02X}"
        level = HEX_TO_LEVEL.get(power_code)
        power_str = LEVEL_LABELS[level] if level is not None else f"0x{power_code:02X}"
        return f"mode={mode_name} freq={freq}MHz bw={bw_str} power={power_str}"

    if type_byte == c.TYPE_STATUS_QUERY:
        return "Status Query"

    if type_byte == c.TYPE_ADDR_QUERY:
        return "Address Query"

    if type_byte == c.TYPE_ADDR_SET and len(buf) == 1:
        return f"Address Set: {buf[0]}"

    return f"Unrecognized command type 0x{type_byte:02X}"


@dataclass
class ParsedFrame:
    type: int
    addr: int
    buf: bytes
    raw: bytes

    def describe(self) -> str:
        if self.type in (c.TYPE_OUTPUT_SWITCH, c.TYPE_SIGNAL_CONTROL) and len(self.buf) == 1:
            code = self.buf[0]
            if code == c.RESP_SUCCESS:
                return "Control succeeded"
            elif code == c.RESP_FAILED:
                return "Control failed"
            else:
                return f"Other/unknown response code: 0x{code:02X}"

        if self.type == c.TYPE_STATUS_QUERY and len(self.buf) >= 6:
            output = self.buf[0]
            mode = self.buf[1]
            freq = struct.unpack(">H", self.buf[2:4])[0]
            bw_code = self.buf[4]
            pw_code = self.buf[5]
            return (
                f"Status: output={'ON' if output else 'OFF'}, "
                f"mode={c.MODE_NAMES.get(mode, mode)}, "
                f"freq={freq}MHz, "
                f"bw={c.BANDWIDTH_CODES_REV.get(bw_code, bw_code)}MHz, "
                f"power_code=0x{pw_code:02X}"
            )

        if self.type == c.TYPE_ADDR_QUERY and len(self.buf) == 1:
            return f"Module address = {self.buf[0]}"

        if self.type == c.TYPE_ADDR_SET and len(self.buf) == 1:
            code = self.buf[0]
            return "Address set OK" if code == c.RESP_SUCCESS else "Address set failed"

        return f"Unrecognized/short payload for type 0x{self.type:02X}"
