import random

from PySide6.QtWidgets import QWidget, QComboBox, QPushButton, QSizePolicy
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QFont

from .card import Card
from styles import theme_colors
from state.level_map import HEX_TO_LEVEL
from services.protocol import constants as c
from hooks.use_channels import MAX_CHANNELS

AXIS_H = 14
REDRAW_MS = 1000  # same cadence as sdr_c's own spectrum redraw (tied to its 1s uptime tick)

_LEVEL_PEAK_PCT = {0: 0, 1: 40, 2: 70, 3: 100}


def _level_trace_color(level: int) -> str:
    # Not a module-level dict - theme_colors' values would be frozen
    # in at import time and go stale after a theme toggle.
    return {
        0: theme_colors.TEXT_MUTED, 1: theme_colors.STATUS_OK,
        2: theme_colors.WARNING_BORDER, 3: theme_colors.STATUS_ERROR,
    }.get(level, theme_colors.TEXT_MUTED)

# sdr_c's real, fixed per-channel operating bands (channels.c) - used
# here purely for the spectrum plot's caption/frequency axis, exactly
# as sdr_c itself displays them. sdr_app's actual Signal Control frames
# still send the shared blind-default frequency/bandwidth regardless of
# which channel (see services/protocol/constants.py's BLIND_DEFAULT_*)
# - that's a separate, real protocol behavior this display doesn't
# change, only visualizes what the hardware's true bands are.
CHANNEL_FREQ_MHZ = [
    753, 859, 920, 1470, 1795, 2045, 2325, 2375,
    2450, 3375, 3550, 3725, 5250, 5450, 5650, 5875,
]
CHANNEL_BANDWIDTH_MHZ = [
    100, 50, 100, 100, 150, 250, 50, 50,
    100, 150, 200, 150, 200, 200, 200, 250,
]


def _jitter(amplitude: int) -> int:
    if amplitude <= 0:
        return 0
    return random.randint(-amplitude, amplitude)


def _white_noise_height_pct(px: int, w: int, peak_pct: int) -> int:
    """Trace shape for Pseudo Random Noise - the only mode this app ever
    sends now: a noisy fundamental block a bit under peak, plus a
    smaller second-harmonic bump, both scaled by the channel's level.
    Direct port of spectrum_height_pct()'s PROTO_MODE_WHITE_NOISE case -
    the other mode shapes (Comb, Linear Sweep, CW) aren't ported since
    this app can't produce them anymore (see channel_card.py's history)."""
    fund_lo, fund_hi = w * 28 // 100, w * 46 // 100
    harm_lo, harm_hi = w * 66 // 100, w * 80 // 100
    val = 1 + _jitter(2)
    if fund_lo <= px <= fund_hi:
        val = peak_pct - 6 + _jitter(9)
    elif harm_lo <= px <= harm_hi:
        val = peak_pct * 28 // 100 + _jitter(6)
    return max(0, min(100, val))


class SpectrumPlot(QWidget):
    """Not a capture - this app has no receiver - but not a guess
    either: every channel's level/on-off is exactly what this app
    commanded, so the trace's peak height and the caption/axis MHz come
    from real, known state. Direct port of sdr_c's spectrum panel
    (spectrum_plot_subclass_proc and friends in main.c)."""

    def __init__(self, channels, parent=None):
        super().__init__(parent)
        self.channels = channels
        self.show_all = True
        self.unit_index = 0
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._label_font = QFont()
        self._label_font.setPointSize(8)

    def set_show_all(self):
        self.show_all = True
        self.update()

    def set_unit(self, index: int):
        self.unit_index = index
        self.show_all = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        painter.fillRect(rect, QColor(theme_colors.FIELD_BG))

        grid_rect = QRect(rect)
        if not self.show_all:
            grid_rect.setBottom(grid_rect.bottom() - AXIS_H)
        self._draw_grid(painter, grid_rect)

        if self.show_all:
            self._draw_all(painter, rect)
        else:
            self._draw_single(painter, rect, grid_rect)

    def _draw_grid(self, painter: QPainter, rect: QRect):
        # COLOR_APP_MUTED, not the panel border color - sdr_c's own fix
        # for the border shade being too close to the field background
        # to actually see.
        painter.setPen(QPen(QColor(theme_colors.TEXT_MUTED), 1))
        w, h = rect.width(), rect.height()
        for i in range(1, 4):
            y = rect.top() + h * i // 4
            painter.drawLine(rect.left(), y, rect.right(), y)
        for i in range(1, 4):
            x = rect.left() + w * i // 4
            painter.drawLine(x, rect.top(), x, rect.bottom())

    def _draw_all(self, painter: QPainter, rect: QRect):
        cols, rows = 4, 4
        total_w, total_h = rect.width(), rect.height()
        for i in range(MAX_CHANNELS):
            col, row = i % cols, i // cols
            left = rect.left() + col * total_w // cols + 3
            right = rect.left() + (col + 1) * total_w // cols - 3
            top = rect.top() + row * total_h // rows + 2
            bottom = rect.top() + (row + 1) * total_h // rows - 2
            cell = QRect(left, top, right - left, bottom - top)
            state = self.channels.get_state(i)
            self._draw_channel_spectrum(painter, cell, state, label=str(i + 1))

    def _draw_single(self, painter: QPainter, rect: QRect, grid_rect: QRect):
        state = self.channels.get_state(self.unit_index)
        d = state.data
        mode_name = c.MODE_NAMES[c.MODE_WHITE_NOISE]
        caption = mode_name if d.output_on else f"{mode_name} - STANDBY"
        self._draw_channel_spectrum(painter, grid_rect, state, caption=caption)

        axis_rect = QRect(rect.left(), grid_rect.bottom(), rect.width(), AXIS_H)
        freq = CHANNEL_FREQ_MHZ[self.unit_index]
        half_bw = CHANNEL_BANDWIDTH_MHZ[self.unit_index] // 2
        painter.setFont(self._label_font)
        painter.setPen(QColor(theme_colors.TEXT_MUTED))
        lo_rect = QRect(grid_rect.left(), axis_rect.top(), 60, axis_rect.height())
        hi_rect = QRect(grid_rect.right() - 60, axis_rect.top(), 60, axis_rect.height())
        painter.drawText(lo_rect, Qt.AlignLeft | Qt.AlignVCenter, str(freq - half_bw))
        painter.drawText(hi_rect, Qt.AlignRight | Qt.AlignVCenter, str(freq + half_bw))

    def _draw_channel_spectrum(self, painter: QPainter, rect: QRect, state,
                                label: str | None = None, caption: str | None = None):
        w, h = rect.width(), rect.height()
        floor_y = rect.bottom() - 2

        painter.setPen(QPen(QColor(theme_colors.BORDER_SUBTLE), 1))
        painter.drawLine(rect.left(), floor_y, rect.right(), floor_y)

        d = state.data
        on = d.output_on

        painter.setFont(self._label_font)
        if label is not None:
            painter.setPen(QColor(theme_colors.TEXT_DARK if on else theme_colors.TEXT_MUTED))
            painter.drawText(rect.left(), rect.top() + 10, label)
        if caption is not None:
            painter.setPen(QColor(theme_colors.TEXT_MUTED))
            painter.drawText(rect.left(), rect.top() + 12, caption)

        # Only draws while actually on - this app's own remembered
        # state (can read true after a restart before anything's been
        # re-sent, e.g. restored from channels.ini), not a live
        # confirmed link. The point is this trace is real commanded
        # state, not a guess.
        if not on or w < 12 or h < 10:
            return

        level = HEX_TO_LEVEL.get(d.power_code, d.last_level)
        peak_pct = _LEVEL_PEAK_PCT.get(level, 0)
        painter.setPen(QPen(QColor(_level_trace_color(level)), 1))

        n = min(w, 360)
        prev_x, prev_y = rect.left(), floor_y
        for px in range(n + 1):
            sample_px = min(px * w // n, w) if n else 0
            x = rect.left() + sample_px
            if px == n:
                y = floor_y
            else:
                pct = _white_noise_height_pct(sample_px, w, peak_pct)
                y = floor_y - h * pct // 100
            painter.drawLine(prev_x, prev_y, x, y)
            prev_x, prev_y = x, y


class SpectrumPanel(Card):

    def __init__(self, channels, parent=None):
        super().__init__("Spectrum", parent=parent)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems([str(i + 1) for i in range(MAX_CHANNELS)])
        self.unit_combo.setFixedWidth(56)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_selected)
        self.header_layout.addWidget(self.unit_combo)

        self.all_btn = QPushButton("All")
        self.all_btn.setCursor(Qt.PointingHandCursor)
        self.all_btn.setFixedWidth(48)
        self.all_btn.setStyleSheet(
            f"QPushButton {{ background: {theme_colors.NAVY}; color: {theme_colors.ACCENT_BLUE}; border: 1px solid {theme_colors.NAVY}; "
            f"border-radius: 5px; font-size: 11px; padding: 3px 0; }}"
            f"QPushButton:hover {{ background: {theme_colors.ACCENT_BLUE_DARK}; }}"
        )
        self.all_btn.clicked.connect(self._on_all_clicked)
        self.header_layout.addWidget(self.all_btn)

        self.plot = SpectrumPlot(channels)
        self.body_layout.addWidget(self.plot, 1)

        self._redraw_timer = QTimer(self)
        self._redraw_timer.timeout.connect(self.plot.update)
        self._redraw_timer.start(REDRAW_MS)

    def _on_unit_selected(self, index: int):
        if index < 0:
            return
        self.plot.set_unit(index)

    def _on_all_clicked(self):
        self.plot.set_show_all()
