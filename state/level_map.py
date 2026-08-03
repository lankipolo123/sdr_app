# Maps the customer-facing 4-position Level slider (L0-L3) to the
# existing protocol's Power dB values (protocol/constants.py POWER_CODES).
#
# L0 is a distinct OFF state - handled via turn_output_off(), never sent
# as a Signal Control power value. It is NOT the same thing as "0 dB":
# L3 is the existing "0 dB (max)" Power option from the old Device
# Control page's dropdown; L0 means no power flowing at all.

LEVEL_TO_DB = {
    0: None,   # L0 = off, no signal command - use turn_output_off()
    1: -12,    # L1
    2: -6,     # L2
    3: 0,      # L3 = 0 dB (max)
}

DB_TO_LEVEL = {db: level for level, db in LEVEL_TO_DB.items() if db is not None}

# If a channel has never had a non-off level set, resume to this on toggle-on.
DEFAULT_RESUME_LEVEL = 1

# What each level actually means, for anywhere L0-L3 is shown to the
# customer - short form for tight spaces (slider labels, bulk buttons),
# full form for tooltips.
LEVEL_LABELS = {0: "Off", 1: "Min", 2: "Med", 3: "Max"}
LEVEL_LABELS_FULL = {0: "Off", 1: "Minimum", 2: "Medium", 3: "Maximum"}
