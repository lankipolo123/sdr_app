"""Continuous 5-stop cool-to-hot gradient (green -> yellow -> orange ->
darker orange -> red), direct port of the C rewrite's real
vivid_thermal_color() (main.c) - fixed to actually match it: this used
to be a different, made-up 4-stop blue-start palette that agreed with
neither sdr_c's real colors nor this app's own LEGEND_STOPS
(components/sensor_heatmap.py), which already matched sdr_c - so the
heatmap's legend bar and the blobs it's meant to describe were
disagreeing with each other. A discrete band function is the wrong tool
for the heatmap: 4 real bay readings a couple degrees apart (the normal
case) usually land in the same band, so all 4 corners would get an
identical color and the "scan" would collapse into one flat fill. t is
0..1 (clamped), not an absolute temperature - the heatmap auto-scales
to the current spread of the live readings (see
components/sensor_heatmap.py's heatmap_scale()) so even a 1C difference
between bays stays visibly distinct instead of vanishing into one band.
"""

_STOPS = [
    (70, 170, 90),
    (210, 190, 60),
    (224, 146, 34),
    (196, 90, 24),
    (214, 64, 56),
]


def vivid_thermal_color(t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    n = len(_STOPS)
    scaled = t * (n - 1)
    idx = int(scaled)
    if idx >= n - 1:
        idx = n - 2
    frac = scaled - idx
    r0, g0, b0 = _STOPS[idx]
    r1, g1, b1 = _STOPS[idx + 1]
    return (
        int(r0 + (r1 - r0) * frac),
        int(g0 + (g1 - g0) * frac),
        int(b0 + (b1 - b0) * frac),
    )


def temp_band_color(temp_c: float) -> tuple[int, int, int]:
    """Discrete safe/caution/danger bands for a single numeric readout
    (the rack-wide average) - same bands as the React rewrite's
    tempBandColor()."""
    if temp_c < 20:
        return (107, 114, 128)  # muted gray
    if temp_c < 40:
        return (22, 163, 74)  # green
    if temp_c < 56:
        return (37, 99, 235)  # blue
    if temp_c < 66:
        return (217, 119, 6)  # orange
    return (220, 38, 38)  # red


def heatmap_scale(temperatures: list[float]) -> tuple[float, float]:
    """Min/max across every reading, widened to a 2C floor so a near-
    identical set of readings doesn't collapse the whole scale to a
    single color - same rule as the C rewrite's
    sensor_heatmap_subclass_proc(). With no readings at all, main.c's
    lo/hi both start at 0.0 and never move, so the same 2C-floor
    widening still applies and yields exactly (-1.0, 1.0) - that's
    where its idle legend's "-1.0C"/"1.0C" placeholder comes from, not
    a special no-data string. Always returns a real tuple, matching
    that (never None)."""
    lo, hi = (min(temperatures), max(temperatures)) if temperatures else (0.0, 0.0)
    if hi - lo < 2:
        mid = (hi + lo) / 2
        lo, hi = mid - 1, mid + 1
    return lo, hi
