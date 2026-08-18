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
        mode_name = c.MODE_NAMES.get(mode, "unrecognized mode")
        bandwidth = c.BANDWIDTH_CODES_REV.get(bw_code)
        bw_str = f"{bandwidth}MHz" if bandwidth is not None else "unrecognized bandwidth"
        level = HEX_TO_LEVEL.get(power_code)
        power_str = LEVEL_LABELS[level] if level is not None else "unrecognized power level"
        return f"mode={mode_name} freq={freq}MHz bw={bw_str} power={power_str}"

    if type_byte == c.TYPE_STATUS_QUERY:
        return "Status Query"

    if type_byte == c.TYPE_ADDR_QUERY:
        return "Address Query"

    if type_byte == c.TYPE_ADDR_SET and len(buf) == 1:
        return f"Address Set: {buf[0]}"

    return "Unrecognized command type"


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
                return "Other/unknown response code"

        if self.type == c.TYPE_STATUS_QUERY and len(self.buf) >= 6:
            output = self.buf[0]
            mode = self.buf[1]
            freq = struct.unpack(">H", self.buf[2:4])[0]
            bw_code = self.buf[4]
            pw_code = self.buf[5]
            bw_display = c.BANDWIDTH_CODES_REV.get(bw_code)
            level = HEX_TO_LEVEL.get(pw_code)
            return (
                f"Status: output={'ON' if output else 'OFF'}, "
                f"mode={c.MODE_NAMES.get(mode, 'unrecognized mode')}, "
                f"freq={freq}MHz, "
                f"bw={f'{bw_display}MHz' if bw_display is not None else 'unrecognized bandwidth'}, "
                f"power={LEVEL_LABELS[level] if level is not None else 'unrecognized power level'}"
            )

        if self.type == c.TYPE_ADDR_QUERY and len(self.buf) == 1:
            return f"Module address = {self.buf[0]}"

        if self.type == c.TYPE_ADDR_SET and len(self.buf) == 1:
            code = self.buf[0]
            return "Address set OK" if code == c.RESP_SUCCESS else "Address set failed"

        return "Unrecognized/short payload"
