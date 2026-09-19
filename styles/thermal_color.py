"""Continuous 4-stop cool-to-hot gradient (blue -> orange -> darker
orange -> red), direct port of the C rewrite's vivid_thermal_color().
A discrete band function is the wrong tool for the heatmap: 4 real bay
readings a couple degrees apart (the normal case) usually land in the
same band, so all 4 corners would get an identical color and the "scan"
would collapse into one flat fill. t is 0..1 (clamped), not an absolute
temperature - the heatmap auto-scales to the current spread of the live
readings (see components/sensor_heatmap.py's heatmap_scale()) so even a
1C difference between bays stays visibly distinct instead of vanishing
into one band.
"""

_STOPS = [
    (58, 133, 224),
    (224, 146, 34),
    (196, 110, 24),
    (224, 90, 90),
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


def heatmap_scale(temperatures: list[float]) -> tuple[float, float] | None:
    """Min/max across every reading, widened to a 2C floor so a near-
    identical set of readings doesn't collapse the whole scale to a
    single color - same rule as the C rewrite's
    sensor_heatmap_subclass_proc()."""
    if not temperatures:
        return None
    lo, hi = min(temperatures), max(temperatures)
    if hi - lo < 2:
        mid = (hi + lo) / 2
        lo, hi = mid - 1, mid + 1
    return lo, hi
