# Maps the customer-facing 3-position Level slider (Min/Med/Max) directly
# to the raw hex power-code byte sent on the wire in a Signal Control
# frame - declared once, here, so changing what a level actually
# transmits is a one-line edit to this table instead of chasing a
# dB-to-hex translation layer elsewhere.
#
# Off is not a slider position - it's purely the toggle's job
# (ChannelController.turn_output_off()). The slider only ever shows
# Min/Med/Max, whether output is currently on or off.

LEVEL_TO_HEX = {
    1: 0x02,   # Min
    2: 0x01,   # Med
    3: 0x00,   # Max
}

HEX_TO_LEVEL = {code: level for level, code in LEVEL_TO_HEX.items()}

# If a channel has never had a level set, resume to this on toggle-on.
DEFAULT_RESUME_LEVEL = 1

# What each level actually means, for anywhere Min/Med/Max is shown to
# the customer - short form for tight spaces (slider labels), full form
# for tooltips.
LEVEL_LABELS = {1: "Min", 2: "Med", 3: "Max"}
LEVEL_LABELS_FULL = {1: "Minimum", 2: "Medium", 3: "Maximum"}
