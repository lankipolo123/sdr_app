# sdr_c's real, fixed per-channel operating bands (channels.c) - shown
# on the Spectrum plot's frequency axis/caption and each ChannelCard's
# own frequency line, exactly as sdr_c itself displays them. sdr_app's
# actual Signal Control frames still send the shared blind-default
# frequency/bandwidth regardless of which channel (see
# services/protocol/constants.py's BLIND_DEFAULT_*) - that's a
# separate, real protocol behavior this display doesn't change, only
# visualizes what the hardware's true bands are.
CHANNEL_FREQ_MHZ = [
    753, 859, 920, 1470, 1795, 2045, 2325, 2375,
    2450, 3375, 3550, 3725, 5250, 5450, 5650, 5875,
]
CHANNEL_BANDWIDTH_MHZ = [
    100, 50, 100, 100, 150, 250, 50, 50,
    100, 150, 200, 150, 200, 200, 200, 250,
]
