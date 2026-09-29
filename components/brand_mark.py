from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainter, QBrush, QColor, QPolygonF

from styles import theme_colors

# sdr_c's real logo mark - two dark "signal peak" diamonds flanking a
# blue upward triangle beam. Base points measured directly off sdr_c's
# own draw_app_logo_mark()/LOGO_LEFT_BASE/LOGO_BEAM_BASE (main.c) - a
# 64x64 box at 1x. Single source of truth for this shape: the header
# brand mark and the heatmap's faded watermark both call paint_mark()
# rather than one drawing vectors and the other loading a flat raster
# snapshot of them - a plain PNG has no halo, so at low opacity (the
# watermark's use case) its dark diamonds vanish against a dark
# background and only the high-contrast blue triangle survives,
# reading as "wrong"/incomplete rather than the real two-diamond mark.
_LEFT_BASE = [(-16, -32), (-32, 0), (-16, 32), (0, 0)]
_BEAM_BASE = [(0, 0), (-16, 32), (16, 32)]
BASE_SPAN = 64.0


def _poly(cx, cy, mult, base) -> QPolygonF:
    return QPolygonF([QPointF(cx + x * mult, cy + y * mult) for x, y in base])


def paint_mark(painter: QPainter, cx: float, cy: float, size: float, halo: bool = True):
    """Paints the mark centered at (cx, cy), scaled to fit a `size`x`size`
    box. Caller owns painter state (opacity, antialiasing, save/restore)
    - this only sets brush/pen. `halo` draws the white outline behind
    the dark diamonds first (106% scale) so they still read against a
    dark background, even under a caller-set low opacity - skip it only
    when the mark is already guaranteed high contrast on its own."""
    mult = size / BASE_SPAN
    right_base = [(-x, y) for x, y in _LEFT_BASE]

    if halo:
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        halo_mult = mult * 1.06
        for base in (_LEFT_BASE, right_base, _BEAM_BASE):
            painter.drawPolygon(_poly(cx, cy, halo_mult, base))

    painter.setBrush(QBrush(QColor(66, 66, 66)))
    painter.drawPolygon(_poly(cx, cy, mult, _LEFT_BASE))
    painter.drawPolygon(_poly(cx, cy, mult, right_base))

    painter.setBrush(QBrush(QColor(theme_colors.ACCENT_BLUE_DARK)))
    painter.drawPolygon(_poly(cx, cy, mult, _BEAM_BASE))
