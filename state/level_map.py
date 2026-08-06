# Maps the customer-facing 4-position Level slider (L0-L3) directly to
# the raw hex power-code byte sent on the wire in a Signal Control frame
# - declared once, here, so changing what a level actually transmits is a
# one-line edit to this table instead of chasing a dB-to-hex translation
# layer elsewhere.
#
# L0 is a distinct OFF state - handled via turn_output_off(), never sent
# as a Signal Control power value.

LEVEL_TO_HEX = {
    0: None,   # L0 = off, no signal command - use turn_output_off()
    1: 0x02,   # L1
    2: 0x01,   # L2
    3: 0x00,   # L3 = max
}

HEX_TO_LEVEL = {code: level for level, code in LEVEL_TO_HEX.items() if code is not None}

# If a channel has never had a non-off level set, resume to this on toggle-on.
DEFAULT_RESUME_LEVEL = 1

# What each level actually means, for anywhere L0-L3 is shown to the
# customer - short form for tight spaces (slider labels, bulk buttons),
# full form for tooltips.
LEVEL_LABELS = {0: "Off", 1: "Min", 2: "Med", 3: "Max"}
LEVEL_LABELS_FULL = {0: "Off", 1: "Minimum", 2: "Medium", 3: "Maximum"}
