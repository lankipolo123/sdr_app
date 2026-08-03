import struct
from dataclasses import dataclass, field
from typing import Optional, List

from . import constants as c


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
                f"power={c.POWER_CODES_REV.get(pw_code, pw_code)}dB"
            )

        if self.type == c.TYPE_ADDR_QUERY and len(self.buf) == 1:
            return f"Module address = {self.buf[0]}"

        if self.type == c.TYPE_ADDR_SET and len(self.buf) == 1:
            code = self.buf[0]
            return "Address set OK" if code == c.RESP_SUCCESS else "Address set failed"

        return f"Unrecognized/short payload for type 0x{self.type:02X}"


class FrameParseError(ValueError):
    pass


class FrameParser:
    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> List[ParsedFrame]:
        self._buf.extend(data)
        frames = []
        while True:
            frame = self._try_extract_one()
            if frame is None:
                break
            frames.append(frame)
        return frames

    def _try_extract_one(self) -> Optional[ParsedFrame]:
        head_idx = self._buf.find(c.HEAD)
        if head_idx == -1:
            if len(self._buf) > 1:
                del self._buf[:-1]
            return None
        if head_idx > 0:
            del self._buf[:head_idx]

        if len(self._buf) < 5:
            return None

        type_byte = self._buf[2]
        addr = self._buf[3]
        buf_len = self._buf[4]
        total_len = 5 + buf_len + 2

        if len(self._buf) < total_len:
            return None

        candidate = bytes(self._buf[:total_len])
        stop = candidate[-2:]
        if stop != c.STOP:
            del self._buf[:2]
            return None

        payload = candidate[5:5 + buf_len]
        del self._buf[:total_len]
        return ParsedFrame(type=type_byte, addr=addr, buf=payload, raw=candidate)
