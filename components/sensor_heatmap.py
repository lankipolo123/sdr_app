import os

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QLinearGradient, QBrush, QPixmap, QFont

from styles import theme_colors
from styles.thermal_color import vivid_thermal_color, heatmap_scale
from utils.app_paths import resource_path

MUTED_COLOR = QColor(156, 163, 175)  # #9CA3AF
LEGEND_H = 22
PANEL_RADIUS = 10


class SensorHeatmap(QWidget):
    """4-bay temperature heatmap - direct visual port of the C rewrite's
    sensor_heatmap_subclass_proc(): each bay gets its own radial "heat
    origin" centered on its own corner (Qt's native QRadialGradient here,
    where the C rewrite fakes one with layered alpha-blended GDI
    circles), auto-scaled to the current spread of live readings, plus a
    legend bar and a faded emblem watermark."""

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
        panel_rect = rect.adjusted(0, 0, 0, -LEGEND_H)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(theme_colors.CONTENT_BG)))
        painter.drawRoundedRect(panel_rect, PANEL_RADIUS, PANEL_RADIUS)
        painter.setClipRect(panel_rect)

        units = self.sensor.units
        readings = [u.temperature_c for u in units if u.has_reading]
        scale = heatmap_scale(readings)

        colors = []
        for u in units:
            if u.has_reading and scale is not None:
                lo, hi = scale
                t = (u.temperature_c - lo) / (hi - lo) if hi > lo else 0.5
                r, g, b = vivid_thermal_color(t)
                colors.append(QColor(r, g, b))
            else:
                colors.append(MUTED_COLOR)

        corners = [panel_rect.topLeft(), panel_rect.topRight(), panel_rect.bottomLeft(), panel_rect.bottomRight()]
        blob_radius = min(panel_rect.width(), panel_rect.height()) * 0.75

        for corner, color in zip(corners, colors):
            gradient = QRadialGradient(corner, blob_radius)
            bright = QColor(color)
            bright.setAlpha(150)
            fade = QColor(color)
            fade.setAlpha(0)
            gradient.setColorAt(0.0, bright)
            gradient.setColorAt(1.0, fade)
            painter.setBrush(QBrush(gradient))
            painter.drawRect(panel_rect)

        # Faded emblem watermark, centered - same idiom the C rewrite's
        # draw_app_logo_faded() uses for its idle signal-wave area and
        # this heatmap panel, direct request to put one here too.
        if self._emblem is not None:
            size = int(min(panel_rect.width(), panel_rect.height()) * 0.4)
            scaled = self._emblem.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.setOpacity(0.12)
            painter.drawPixmap(
                int(panel_rect.center().x() - scaled.width() / 2),
                int(panel_rect.center().y() - scaled.height() / 2),
                scaled,
            )
            painter.setOpacity(1.0)

        # Floating "BAY N" / reading at each corner, matching the C
        # rewrite's corner layout: 0=top-left, 1=top-right,
        # 2=bottom-left, 3=bottom-right.
        label_font = QFont()
        label_font.setPointSize(7)
        label_font.setBold(True)
        reading_font = QFont()
        reading_font.setPointSize(9)
        reading_font.setBold(True)

        pad = 6
        label_boxes = [
            (QRectF(panel_rect.left() + pad, panel_rect.top() + pad, 90, 30), Qt.AlignLeft | Qt.AlignTop),
            (QRectF(panel_rect.right() - 90 - pad, panel_rect.top() + pad, 90, 30), Qt.AlignRight | Qt.AlignTop),
            (QRectF(panel_rect.left() + pad, panel_rect.bottom() - 30 - pad, 90, 30), Qt.AlignLeft | Qt.AlignBottom),
            (QRectF(panel_rect.right() - 90 - pad, panel_rect.bottom() - 30 - pad, 90, 30), Qt.AlignRight | Qt.AlignBottom),
        ]
        for unit, color, (box, align) in zip(units, colors, label_boxes):
            painter.setFont(label_font)
            painter.setPen(QColor(theme_colors.TEXT_MUTED))
            painter.drawText(box, align, f"BAY {unit.address}")
            painter.setFont(reading_font)
            painter.setPen(color if unit.has_reading else QColor(theme_colors.TEXT_MUTED))
            reading_box = QRectF(box.x(), box.y() + 12, box.width(), box.height() - 12)
            if unit.has_reading:
                text = f"{unit.temperature_c:.1f}°C"
            elif unit.online:
                text = "Reading…"
            else:
                text = "-"
            painter.drawText(reading_box, align, text)

        painter.setClipping(False)

        # Legend: colors are auto-scaled to the CURRENT spread of
        # readings, not a fixed scale - a color alone no longer tells
        # you an absolute temperature, so spell out what the current
        # lo/hi actually is.
        legend_rect = QRectF(rect.left(), rect.bottom() - LEGEND_H + 5, rect.width(), 8)
        bar_rect = legend_rect.adjusted(36, 0, -36, 0)
        gradient = QLinearGradient(bar_rect.topLeft(), bar_rect.topRight())
        for stop_t in (0.0, 1 / 3, 2 / 3, 1.0):
            r, g, b = vivid_thermal_color(stop_t)
            gradient.setColorAt(stop_t, QColor(r, g, b))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(bar_rect, 3, 3)

        painter.setFont(label_font)
        painter.setPen(QColor(theme_colors.TEXT_MUTED))
        lo_text = f"{scale[0]:.1f}°C" if scale else "-"
        hi_text = f"{scale[1]:.1f}°C" if scale else "-"
        painter.drawText(QRectF(rect.left(), legend_rect.top() - 3, 34, 14), Qt.AlignLeft | Qt.AlignVCenter, lo_text)
        painter.drawText(
            QRectF(rect.right() - 34, legend_rect.top() - 3, 34, 14), Qt.AlignRight | Qt.AlignVCenter, hi_text
        )

        painter.end()
