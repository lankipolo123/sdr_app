
LEVEL_TO_HEX = {
    0: None,
    1: 0x02,
    2: 0x01,
    3: 0x00,
}

HEX_TO_LEVEL = {code: level for level, code in LEVEL_TO_HEX.items() if code is not None}

DEFAULT_RESUME_LEVEL = 1

LEVEL_LABELS = {0: "Off", 1: "Low", 2: "Med", 3: "High"}
LEVEL_LABELS_FULL = {0: "Off", 1: "Low", 2: "Medium", 3: "High"}
