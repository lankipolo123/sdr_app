HEAD = b"\x7E\x7E"
STOP = b"\x0A\x0D"

BROADCAST_ADDR = 0xFF

TYPE_OUTPUT_SWITCH = 0x01
TYPE_SIGNAL_CONTROL = 0x02
TYPE_STATUS_QUERY = 0xFF
TYPE_ADDR_QUERY = 0xBF
TYPE_ADDR_SET = 0xB1

OUTPUT_OFF = 0x00
OUTPUT_ON = 0x01

MODE_WHITE_NOISE = 0x00
MODE_LINEAR_SWEEP = 0x01
MODE_COMB_SPECTRUM = 0x02
MODE_SINGLE = 0x03

MODE_NAMES = {
    MODE_WHITE_NOISE: "Pseudo Random Noise",
    MODE_LINEAR_SWEEP: "Linear Sweep",
    MODE_COMB_SPECTRUM: "Multi-tone",
    MODE_SINGLE: "Continuous Wave (CW)",
}

MODES_UNCONFIRMED = frozenset({MODE_SINGLE})

BANDWIDTH_CODES = {
    10: 0x00,
    20: 0x01,
    50: 0x02,
    100: 0x03,
    150: 0x04,
    200: 0x05,
    250: 0x06,
    300: 0x07,
}
BANDWIDTH_CODES_REV = {v: k for k, v in BANDWIDTH_CODES.items()}

BANDWIDTH_UNCONFIRMED = frozenset({300})

RESP_FAILED = 0x01
RESP_SUCCESS = 0xFF

FREQ_MIN_MHZ = 300
FREQ_MAX_MHZ = 6000

ADDR_MIN = 0
ADDR_MAX = 199

# Only used when sending a Power/level command "blind" - a channel that
# has never been discovered has no real Mode/Frequency/Bandwidth
# baseline, and a Signal Control frame requires all three fields
# alongside Power in one command. These are a guess, not a confirmed
# value - explicitly accepted as a real risk (an incorrect frequency/
# bandwidth actually changes RF behavior, unlike an unconfirmed
# Output ON/OFF) so blind-send can work on an address with no baseline
# yet, same as Output ON/OFF already could.
BLIND_DEFAULT_MODE = MODE_WHITE_NOISE
BLIND_DEFAULT_FREQ_MHZ = 2450
BLIND_DEFAULT_BANDWIDTH_MHZ = 100
