import math

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QFileDialog, QWidget, QAbstractButton, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QFontMetrics, QPainterPath, QLinearGradient

from .card import Card
from styles import theme_colors
from styles.thermal_color import vivid_thermal_color
from utils.channel_store import load_channel_states, save_channel_states
from state.level_map import LEVEL_TO_HEX

READOUT_H = 72
MODE_ICON_SIZE = 64


def _cmd_btn_style() -> str:
    return (
        f"QPushButton {{ background: {theme_colors.NAVY}; color: {theme_colors.ACCENT_BLUE}; border: 1px solid {theme_colors.NAVY}; "
        f"border-radius: 5px; font-size: 11px; font-weight: 600; padding: 8px 4px; }}"
        f"QPushButton:hover {{ background: {theme_colors.ACCENT_BLUE}; color: {theme_colors.NAVY}; }}"
    )


def _colored_btn(text: str, bg: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background: {bg}; border: 1px solid {bg}; border-radius: 5px; "
        f"padding: 8px 4px; font-size: 11px; font-weight: 600; color: white; }}"
        f"QPushButton:hover {{ background: {bg}; }}"
    )
    return btn


class _GradientReadout(QWidget):
    """AVG TEMP / Highest Temp Today's own content block - direct port
    of avg_temp_block_subclass_proc()/highest_temp_block_subclass_proc()
    (main.c): no pill/box background (blends straight into the Summary
    card behind it), the number's own glyph shapes filled with a real
    cool-to-hot gradient (BeginPath/TextOutA/EndPath -> PathToRegion's
    glyph-shaped clip there; QPainterPath + setClipPath here), left =
    vivid_thermal_color(0.0), right = vivid_thermal_color(1.0) -
    decorative, not actually mapped to the shown temperature. Falls
    back to small plain muted text (not the gradient treatment - a
    single "-"/"No Data" run through a glyph-shaped clip rendered as an
    unreadable smudge, direct report in main.c) when there's no value
    yet."""

    def __init__(self, point_size: int, parent=None):
        super().__init__(parent)
        self._point_size = point_size
        self._text = ""
        self._muted = True
        self.setFixedHeight(READOUT_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, text: str, muted: bool):
        self._text = text
        self._muted = muted
        self.update()

    def paintEvent(self, event):
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        font = QFont()
        font.setBold(not self._muted)
        font.setPointSize(11 if self._muted else self._point_size)
        metrics = QFontMetrics(font)
        text_w = metrics.horizontalAdvance(self._text)
        x = (rect.width() - text_w) / 2
        y = (rect.height() - metrics.height()) / 2 + metrics.ascent()

        if self._muted:
            painter.setFont(font)
            painter.setPen(QColor(theme_colors.TEXT_MUTED))
            painter.drawText(rect, Qt.AlignCenter, self._text)
            return

        path = QPainterPath()
        path.addText(x, y, font, self._text)
        painter.setClipPath(path)
        # Spans the TEXT's own width, not the widget's - sdr_c's block
        # width is close to its g_huge_font text width, so the same
        # "gradient across the whole rect" reads as a full blue-to-red
        # sweep there; here the block is much wider than the text, so
        # doing the same would only ever paint a narrow, mostly-one-
        # color slice of the gradient.
        gradient = QLinearGradient(x, 0, x + text_w, 0)
        r0, g0, b0 = vivid_thermal_color(0.0)
        r1, g1, b1 = vivid_thermal_color(1.0)
        gradient.setColorAt(0.0, QColor(r0, g0, b0))
        gradient.setColorAt(1.0, QColor(r1, g1, b1))
        painter.fillRect(rect, gradient)


class _ModeToggleIcon(QAbstractButton):
    """Summary card's Mode toggle - icon only, no button background/
    badge, direct port of the WM_DRAWITEM branch for
    IDC_THEME_TOGGLE_BTN (main.c): a moon while in Dark mode, a sun
    while in Light mode - the CURRENT mode, not the destination
    clicking it switches to (the opposite of the old text-button
    version's "Light Mode"/"Dark Mode" label, which showed the
    destination - main.c replaced that button with this same icon,
    same ID, same on_theme_toggle_clicked(), just redrawn)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(MODE_ICON_SIZE, MODE_ICON_SIZE)
        self.setToolTip("Switch Light/Dark mode")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        rect = self.rect()
        icx, icy = rect.center().x(), rect.center().y()

        if theme_colors.is_light_mode():
            sun_color = QColor(255, 196, 0)
            painter.setBrush(QBrush(sun_color))
            body_r = rect.width() * 0.17
            painter.drawEllipse(QPointF(icx, icy), body_r, body_r)
            pen = QPen(sun_color)
            pen.setWidth(max(2, round(rect.width() * 0.045)))
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            ray_lo, ray_hi = rect.width() * 0.23, rect.width() * 0.33
            for i in range(8):
                angle = i * math.pi / 4
                dx, dy = math.cos(angle), math.sin(angle)
                painter.drawLine(
                    QPointF(icx + dx * ray_lo, icy + dy * ray_lo),
                    QPointF(icx + dx * ray_hi, icy + dy * ray_hi),
                )
        else:
            moon_color = QColor(theme_colors.ACCENT_BLUE)
            painter.setBrush(QBrush(moon_color))
            main_r = rect.width() * 0.30
            painter.drawEllipse(QPointF(icx, icy), main_r, main_r)
            # Mask ellipse painted in the Card's own background color -
            # same "fake a crescent by overpainting in the bg color"
            # trick main.c uses, since neither GDI nor QPainter can
            # subtract one shape from another directly.
            painter.setBrush(QBrush(QColor(theme_colors.SURFACE)))
            mask_r = main_r * 1.25
            offset = main_r * 0.55
            painter.drawEllipse(QPointF(icx + offset, icy - offset), mask_r, mask_r)


class SummaryPanel(Card):
    """The big wide card sdr_c puts below its channel grid, not above
    it: Commands (rack-wide actions - not gated by Bulk Actions'
    checkbox selection, these always hit every channel), the rack's
    AVG TEMP and Highest Temp Today readings, and a Mode block with
    the Light/Dark toggle. Direct port of main.c's g_summary_panel -
    minus "Open Csv Logs" (this app has no CSV log) and "Icon" (already
    reachable from the title bar's Change Logo)."""

    theme_toggle_requested = Signal()

    def __init__(self, app_controller, parent=None):
        super().__init__("Summary", icon="sliders-h.png", parent=parent)
        self.app = app_controller

        row = QHBoxLayout()
        row.setSpacing(16)

        # ---- Commands ----
        commands_col = QVBoxLayout()
        commands_col.setSpacing(6)
        commands_col.addWidget(_section_label("Commands"))

        grid = QGridLayout()
        grid.setSpacing(6)

        shutdown_btn = _colored_btn("Emergency Shutdown", theme_colors.STATUS_ERROR)
        shutdown_btn.clicked.connect(self._on_emergency_shutdown)
        grid.addWidget(shutdown_btn, 0, 0)

        activate_btn = _colored_btn("Global Activate", theme_colors.STATUS_OK)
        activate_btn.clicked.connect(self._on_global_activate)
        grid.addWidget(activate_btn, 0, 1)

        load_btn = QPushButton("Load Config")
        load_btn.setCursor(Qt.PointingHandCursor)
        load_btn.setStyleSheet(_cmd_btn_style())
        load_btn.clicked.connect(self._on_load_config_clicked)
        grid.addWidget(load_btn, 1, 0)

        save_btn = QPushButton("Save Config")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(_cmd_btn_style())
        save_btn.clicked.connect(self._on_save_config_clicked)
        grid.addWidget(save_btn, 1, 1)

        reset_btn = QPushButton("Reset to Default")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setStyleSheet(_cmd_btn_style())
        reset_btn.clicked.connect(self._on_reset_to_default)
        grid.addWidget(reset_btn, 2, 0, 1, 2)

        commands_col.addLayout(grid)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {theme_colors.TEXT_MUTED}; font-size: 11px;")
        self.status_label.setWordWrap(True)
        commands_col.addWidget(self.status_label)
        commands_col.addStretch(1)

        row.addLayout(commands_col, 2)
        row.addWidget(_divider())

        # ---- AVG TEMP ----
        avg_col = QVBoxLayout()
        avg_col.setSpacing(6)
        avg_col.addWidget(_section_label("AVG TEMP"))
        self.avg_readout = _GradientReadout(point_size=28)
        avg_col.addWidget(self.avg_readout)
        avg_col.addStretch(1)
        row.addLayout(avg_col, 1)

        row.addWidget(_divider())

        # ---- Highest Temp Today ----
        highest_col = QVBoxLayout()
        highest_col.setSpacing(6)
        highest_col.addWidget(_section_label("Highest Temp Today"))
        self.highest_readout = _GradientReadout(point_size=15)
        highest_col.addWidget(self.highest_readout)
        highest_col.addStretch(1)
        row.addLayout(highest_col, 1)

        row.addWidget(_divider())

        # ---- Mode ----
        mode_col = QVBoxLayout()
        mode_col.setSpacing(6)
        mode_col.addWidget(_section_label("Mode"))
        self.mode_icon = _ModeToggleIcon()
        self.mode_icon.clicked.connect(self._on_mode_toggle_clicked)
        mode_col.addWidget(self.mode_icon, 0, alignment=Qt.AlignLeft)
        mode_col.addStretch(1)
        row.addLayout(mode_col, 0)

        self.body_layout.addLayout(row)

        self.app.sensor.changed.connect(self.refresh_temps)
        self.refresh_temps()

    def _on_mode_toggle_clicked(self):
        self.theme_toggle_requested.emit()

    def refresh_temps(self):
        avg = self.app.sensor.average_temperature()
        if avg is None:
            self.avg_readout.set_value("--.-C", muted=True)
        else:
            self.avg_readout.set_value(f"{avg:.1f}C", muted=False)

        highest = self.app.sensor.highest_temp_today_c
        if highest is None:
            self.highest_readout.set_value("No Data", muted=True)
        else:
            bay = self.app.sensor.highest_temp_today_bay
            self.highest_readout.set_value(f"{highest:.1f}C - BAY{bay}", muted=False)

    def _on_emergency_shutdown(self):
        for controller in self.app.channels.controllers.values():
            controller.turn_output_off()
        self.status_label.setText("Emergency Shutdown: every channel commanded OFF.")

    def _on_global_activate(self):
        skipped = 0
        for address, controller in self.app.channels.controllers.items():
            if self.app.safety.allow_power_on(address):
                controller.turn_output_on()
            else:
                skipped += 1
        status = "Global Activate: every channel commanded ON"
        status += f" ({skipped} skipped - kill switch tripped)." if skipped else "."
        self.status_label.setText(status)

    def _on_reset_to_default(self):
        # sdr_c's version also force-sets every channel's mode to
        # Pseudo Random Noise - a no-op here, since that's the only
        # mode this app ever sends.
        skipped = 0
        for address, controller in self.app.channels.controllers.items():
            if self.app.safety.allow_power_on(address):
                controller.turn_output_on()
            else:
                skipped += 1
        status = "Reset to Default: every channel set to Pseudo Random Noise, ON"
        status += f" ({skipped} skipped - kill switch tripped)." if skipped else "."
        self.status_label.setText(status)

    def _on_save_config_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config", "channels.ini", "Config files (*.ini)"
        )
        if not path:
            return
        save_channel_states(self.app.channels.states, path)
        self.status_label.setText("Config saved.")

    def _on_load_config_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Config", "", "Config files (*.ini)"
        )
        if not path:
            return
        saved_states = load_channel_states(path)
        applied = 0
        skipped = 0
        for address, entry in saved_states.items():
            controller = self.app.channels.controllers.get(address)
            if controller is None:
                continue
            output_on = entry.get("output_on", False)
            level = entry.get("last_level", 0) if output_on else 0
            code = LEVEL_TO_HEX[level]
            if code is not None and not self.app.safety.allow_power_on(address):
                skipped += 1
                continue
            if code is None:
                controller.turn_output_off()
            elif controller.state.data.output_on:
                controller.set_power(code)
            else:
                controller.resume_output(code)
            applied += 1
        status = f"Config loaded: {applied} applied"
        status += f", {skipped} skipped (kill switch tripped)." if skipped else "."
        self.status_label.setText(status)


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {theme_colors.TEXT_DARK}; font-size: 11px; font-weight: 700;")
    return lbl


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setStyleSheet(f"color: {theme_colors.BORDER_SUBTLE};")
    return line
