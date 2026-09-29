# sdr_c's real, fixed per-channel operating bands (channels.c) - shown
# on the Spectrum plot's frequency axis/caption and each ChannelCard's
# own frequency line, exactly as sdr_c itself displays them, AND the
# actual values every real Signal Control frame sends (hooks/use_channel.py's
# set_power()/set_mode() - direct fix, this used to fall back to one
# shared blind-default frequency/bandwidth for every channel instead,
# a real wrong-frequency risk on 15 of 16 channels' first command).
CHANNEL_FREQ_MHZ = [
    753, 859, 920, 1470, 1795, 2045, 2325, 2375,
    2450, 3375, 3550, 3725, 5250, 5450, 5650, 5875,
]
CHANNEL_BANDWIDTH_MHZ = [
    100, 50, 100, 100, 150, 250, 50, 50,
    100, 150, 200, 150, 200, 200, 200, 250,
]
