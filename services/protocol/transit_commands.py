# DLL-token-based commands for Transit.dll's real, confirmed vocabulary
# (see services/test_command_tokens.py's KNOWN_TABLE for the X#0..X#P/XME/
# XOP/etc alias table) - distinct from commands.py's RS-422 byte frames,
# which were built on unconfirmed guesses (see services/test_transit_dll.py's
# SEND_ATTEMPTS). channel_select_tokens() below is the first confirmed
# real command: everything but ch_tok and the two per-channel tokens after
# X#E {ch_module} is a fixed template - ch_module/ch_attn are opaque,
# caller-supplied values, just slotted into place, never interpreted here.
#
# Per-channel (ch_tok, num_tok, mid_tok) triple - not a derivable formula
# (mid_tok doesn't follow channel number), so it's a lookup table, not
# computed.
_CHANNEL_TOKENS = {
    1:  ("X#A", "X#1F",  "X#D"),
    2:  ("X#B", "X#2F",  "X#C"),
    3:  ("X#C", "X#3F",  "X#C"),
    4:  ("X#D", "X#4F",  "X#C"),
    5:  ("X#E", "X#5F",  "X#E"),
    6:  ("X#F", "X#6F",  "X#F"),
    7:  ("X#G", "X#7F",  "X#C"),
    8:  ("X#H", "X#8F",  "X#B"),
    9:  ("X#I", "X#9F",  "X#C"),
    10: ("X#J", "X#AF",  "X#D"),
    11: ("X#K", "X#BF",  "X#E"),
    12: ("X#L", "X#CF",  "X#D"),
    13: ("X#M", "X#DF",  "X#E"),
    14: ("X#N", "X#EF",  "X#E"),
    15: ("X#O", "X#FF",  "X#E"),
    16: ("X#P", "X#10F", "X#E"),
}


def channel_select_tokens(channel_id: int, ch_module: str, ch_attn: str) -> str:
    ch_tok, num_tok, mid_tok = _CHANNEL_TOKENS.get(channel_id, _CHANNEL_TOKENS[1])
    return f"XME XME X#B {ch_tok} X#E {ch_module} {num_tok} {mid_tok} {ch_attn} X#J X#M"
