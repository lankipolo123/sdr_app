import os

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QLinearGradient, QBrush, QPen, QPixmap, QFont, QPainterPath

from styles import theme_colors
from styles.thermal_color import vivid_thermal_color, heatmap_scale
from utils.app_paths import resource_path

LEGEND_H = 22
PANEL_RADIUS = 14
DOT_R = 6
HALO_R = 13

# radius_pct/alpha per ring, biggest+faintest first so smaller/more-
# opaque rings layer on top - direct port of sensor_heatmap_subclass_
# proc()'s own `rings` table (main.c). GDI fakes a radial gradient
# with concentric flat-alpha circles since it has no native one;
# same idea here, just via QPainterPath clipping instead of ellipse
# regions.
RINGS = [
    (100, 28), (78, 34), (58, 42), (40, 55), (24, 72), (12, 92),
]

# Same 5 stops as vivid_thermal_color(), duplicated for the legend bar
# (a literal left-to-right sweep, not a 0..1 lookup) - matches main.c's
# own duplication of these for exactly the same reason.
LEGEND_STOPS = [
    (0.00, (70, 170, 90)),
    (0.25, (210, 190, 60)),
    (0.50, (224, 146, 34)),
    (0.75, (196, 90, 24)),
    (1.00, (214, 64, 56)),
]


class SensorHeatmap(QWidget):
    """4-bay temperature heatmap - direct visual port of the C rewrite's
    sensor_heatmap_subclass_proc(): each bay gets its own radial "heat
    origin" - concentric alpha-blended rings centered on a small
    accent-ringed marker dot, not a single wash smeared across the
    whole panel - plus a muted 4-corner ambient tint behind them, a
    faded emblem watermark, corner-pinned "BAY N"/reading labels (the
    label is always the outermost line, the reading tucked just inside
    it), and a legend bar spelling out the current auto-scaled lo/hi in
    real degrees. The corner tint is an approximation of main.c's exact
    GDI triangle-fill Gouraud blend (radial glows from each panel
    corner instead of a true 3-color barycentric fill) - QPainter has
    no equivalent primitive, and at this size the difference isn't
    perceptible."""

    def __init__(self, sensor_controller, parent=None):
        super().__init__(parent)
        self.sensor = sensor_controller
        self.setMinimumHeight(150)
        self.sensor.changed.connect(self.update)
        self._emblem = self._load_emblem()

    @staticmethod
    def _load_emblem() -> QPixmap | None:
        path = resource_path("assets", "icons", "app_icon.png")
        if not os.path.exists(path):
            return None
        pixmap = QPixmap(path)
        return pixmap if not pixmap.isNull() else None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect())
        blend_rect = rect.adjusted(0, 0, 0, -LEGEND_H)

        units = self.sensor.units
        readings = [u.temperature_c for u in units if u.has_reading]
        any_reading = bool(readings)
        lo, hi = heatmap_scale(readings)

        idle_color = QColor(205, 207, 211) if theme_colors.is_light_mode() else QColor(theme_colors.TEXT_MUTED)
        colors = []
        for u in units:
            if u.has_reading:
                t = (u.temperature_c - lo) / (hi - lo) if hi > lo else 0.5
                r, g, b = vivid_thermal_color(t)
                colors.append(QColor(r, g, b))
            else:
                colors.append(idle_color)

        # Dot positions - independent of where each "BAY N" label sits
        # (pinned to the panel's own corner, in the label loop below);
        # inset further than the label's corner margin so the dot reads
        # as its own free-floating marker.
        inset_x = blend_rect.width() * 0.34
        inset_y = 28
        dots = [
            QPointF(blend_rect.left() + inset_x, blend_rect.top() + inset_y),
            QPointF(blend_rect.right() - inset_x, blend_rect.top() + inset_y),
            QPointF(blend_rect.left() + inset_x, blend_rect.bottom() - inset_y),
            QPointF(blend_rect.right() - inset_x, blend_rect.bottom() - inset_y),
        ]

        panel_path = QPainterPath()
        panel_path.addRoundedRect(rect, PANEL_RADIUS, PANEL_RADIUS)
        painter.setClipPath(panel_path)

        field_bg = QColor(theme_colors.FIELD_BG)
        painter.fillRect(blend_rect, field_bg)

        # Muted 4-corner ambient wash under the dot-centered rings -
        # see the class docstring for how this differs from main.c's
        # exact technique.
        wash_radius = max(blend_rect.width(), blend_rect.height()) * 0.9
        corner_points = [blend_rect.topLeft(), blend_rect.topRight(), blend_rect.bottomLeft(), blend_rect.bottomRight()]
        painter.setPen(Qt.NoPen)
        for corner_pt, color in zip(corner_points, colors):
            mixed = QColor(
                (color.red() * 9 + field_bg.red() * 91) // 100,
                (color.green() * 9 + field_bg.green() * 91) // 100,
                (color.blue() * 9 + field_bg.blue() * 91) // 100,
            )
            gradient = QRadialGradient(corner_pt, wash_radius)
            bright = QColor(mixed)
            bright.setAlpha(160)
            fade = QColor(mixed)
            fade.setAlpha(0)
            gradient.setColorAt(0.0, bright)
            gradient.setColorAt(1.0, fade)
            painter.setBrush(QBrush(gradient))
            painter.drawRect(blend_rect)

        # Each bay's own radial heat origin. The panel clip set above is
        # still active, so a plain filled ellipse is already clipped to
        # it - no need to intersect a fresh path per ring (28 of those
        # per repaint was measurably slow enough to eat into other
        # timer-driven tests' own budgets).
        painter.setPen(Qt.NoPen)
        blob_radius = min(blend_rect.width(), blend_rect.height()) * 0.7
        for center, color in zip(dots, colors):
            for radius_pct, alpha in RINGS:
                r = blob_radius * radius_pct / 100
                fill = QColor(color)
                fill.setAlpha(alpha)
                painter.setBrush(QBrush(fill))
                painter.drawEllipse(center, r, r)

        # Faded emblem watermark, centered over the blend - same idiom
        # the C rewrite's draw_app_logo_faded() uses for its idle
        # signal-wave area and this heatmap panel. Sized off the panel's
        # SMALLER dimension (height, pinned to HEADER_ROW_HEIGHT to
        # match its row neighbors - see main_page.py) rather than width,
        # so widening the panel alone never grows this - bumped the
        # factor and opacity instead, direct report that it was barely
        # visible at the old 0.4/0.12.
        if self._emblem is not None:
            size = int(min(blend_rect.width(), blend_rect.height()) * 0.62)
            scaled = self._emblem.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.setOpacity(0.24)
            painter.drawPixmap(
                int(blend_rect.center().x() - scaled.width() / 2),
                int(blend_rect.center().y() - scaled.height() / 2),
                scaled,
            )
            painter.setOpacity(1.0)

        # Sensor location marker - a soft accent-blue halo behind a
        # crisp white dot with an accent-blue ring, drawn on top of the
        # blobs/watermark, under the BAY/reading labels below.
        for center in dots:
            halo = QColor(theme_colors.ACCENT_BLUE)
            halo.setAlpha(110)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(center, HALO_R, HALO_R)

            painter.setPen(QPen(QColor(theme_colors.ACCENT_BLUE), 2))
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.drawEllipse(center, DOT_R, DOT_R)

        # Legend: colors are auto-scaled to the CURRENT spread of
        # readings, not a fixed scale - spell out what the current
        # lo/hi actually is.
        legend_rect = QRectF(rect.left(), blend_rect.bottom(), rect.width(), LEGEND_H)
        bar_rect = QRectF(legend_rect.left() + 40, legend_rect.top() + 8, legend_rect.width() - 80, 5)
        if bar_rect.width() > 0:
            gradient = QLinearGradient(bar_rect.left(), 0, bar_rect.right(), 0)
            for pos, (r, g, b) in LEGEND_STOPS:
                gradient.setColorAt(pos, QColor(r, g, b))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(bar_rect, 2, 2)

        legend_font = QFont("Consolas")
        legend_font.setPointSize(9)
        legend_font.setWeight(QFont.DemiBold)
        painter.setFont(legend_font)
        painter.setPen(QColor(theme_colors.TEXT_MUTED))
        lo_rect = QRectF(legend_rect.left() + 6, legend_rect.top(), bar_rect.left() - legend_rect.left() - 10, legend_rect.height())
        hi_rect = QRectF(bar_rect.right() + 4, legend_rect.top(), legend_rect.right() - bar_rect.right() - 10, legend_rect.height())
        painter.drawText(lo_rect, Qt.AlignLeft | Qt.AlignVCenter, f"{lo:.1f}C")
        painter.drawText(hi_rect, Qt.AlignRight | Qt.AlignVCenter, f"{hi:.1f}C")

        painter.setClipping(False)

        # Silver/accent border while at least one bay has a real, live
        # reading - reads as "actively scanning" at a glance, vs. the
        # normal muted border the rest of the time.
        if any_reading:
            border_color = theme_colors.ACCENT_BLUE if theme_colors.is_light_mode() else "#C8CBD1"
        else:
            border_color = theme_colors.BORDER_SUBTLE
        painter.setPen(QPen(QColor(border_color), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), PANEL_RADIUS, PANEL_RADIUS)

        # "BAY N" / reading, pinned to the panel's own corner (NOT the
        # dot's position) so it reads like a map legend entry - the
        # label is always the outermost line, the reading tucked just
        # inside it (reversed order for the bottom row, so it still
        # sits closest to the panel edge there too). Every string is
        # drawn twice, 1px-offset shadow then real text on top, a cheap
        # drop-shadow that stays legible over both ends of the blend.
        label_font = QFont("Consolas")
        label_font.setPointSize(11)
        label_font.setWeight(QFont.DemiBold)
        num_font = QFont("Consolas")
        num_font.setPointSize(16)
        num_font.setBold(True)

        margin = 12
        block_w = 64
        label_h = 14
        num_h = 18
        gap = 2
        reading_text_color = QColor(theme_colors.TEXT_DARK) if theme_colors.is_light_mode() else QColor(255, 255, 255)
        reading_shadow_color = QColor(255, 255, 255) if theme_colors.is_light_mode() else QColor(10, 10, 12)

        for i, unit in enumerate(units):
            left_col = i in (0, 2)
            top_row = i in (0, 1)
            align = (Qt.AlignLeft if left_col else Qt.AlignRight) | Qt.AlignTop

            if left_col:
                col_left = blend_rect.left() + margin
            else:
                col_left = blend_rect.right() - margin - block_w

            if top_row:
                label_rect = QRectF(col_left, blend_rect.top() + margin, block_w, label_h)
                num_rect = QRectF(col_left, label_rect.bottom() + gap, block_w, num_h)
            else:
                label_rect = QRectF(col_left, blend_rect.bottom() - margin - label_h, block_w, label_h)
                num_rect = QRectF(col_left, label_rect.top() - gap - num_h, block_w, num_h)

            blabel = f"BAY {unit.address}"
            num_label = f"{unit.temperature_c:.1f}C" if unit.has_reading else "-"

            painter.setFont(label_font)
            painter.setPen(reading_shadow_color)
            painter.drawText(label_rect.translated(1, 1), align, blabel)
            painter.setPen(QColor(theme_colors.ACCENT_BLUE))
            painter.drawText(label_rect, align, blabel)

            painter.setFont(num_font)
            painter.setPen(reading_shadow_color)
            painter.drawText(num_rect.translated(1, 1), align, num_label)
            painter.setPen(reading_text_color)
            painter.drawText(num_rect, align, num_label)
