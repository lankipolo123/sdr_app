from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor

# 4 vertical bars ascending left to right, like a signal-strength/WiFi
# indicator - fits this app's own RF/signal theme. This is the app's
# real icon now (window/taskbar/splash - see utils/app_paths.py and
# assets/icons/app_icon.png/.ico, regenerated from this exact shape by
# a one-off script, not hand-drawn separately), not just the header
# brand mark's icon - both draw from this single shared function so
# they can never drift apart. Direct request ("the vertical bars...
# as an icon on helix defender", then "make [it] the main icon").
HEIGHT_FRACTIONS = (0.28, 0.52, 0.76, 1.0)


def paint_signal_bars(painter, x: float, y: float, w: float, h: float, color) -> None:
    """Paints the bars inside the box (x, y, w, h). Caller owns painter
    state (pen, antialiasing, brush color already applied via `color`)."""
    painter.setBrush(QBrush(QColor(color)))
    n = len(HEIGHT_FRACTIONS)
    bar_w = w * 0.16
    gap = w * 0.08
    total_w = n * bar_w + (n - 1) * gap
    x0 = x + (w - total_w) / 2
    baseline = y + h * 0.92
    max_bar_h = h * 0.8
    radius = bar_w * 0.25

    for i, frac in enumerate(HEIGHT_FRACTIONS):
        bar_h = max_bar_h * frac
        bx = x0 + i * (bar_w + gap)
        by = baseline - bar_h
        painter.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), radius, radius)
