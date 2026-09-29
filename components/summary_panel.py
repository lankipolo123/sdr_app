import math

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QDialog, QWidget, QAbstractButton, QSizePolicy, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QFontMetrics, QPainterPath, QLinearGradient, QIcon, QPixmap

from .card import Card
from styles import theme_colors
from styles.thermal_color import vivid_thermal_color
from state.level_map import LEVEL_TO_HEX

READOUT_H = 72
MODE_ICON_SIZE = 96
CMD_ICON_SIZE = 18


def _cmd_icon(kind: str, color: QColor) -> QIcon:
    """Hand-drawn line-art matching main.c's own WM_DRAWITEM glyphs for
    these exact buttons - Emergency Shutdown/Global Activate's hollow-
    vs-filled power dot, Load Config's import-into-tray arrow, Save
    Config's floppy disk, Reset to Default's circular reset arrow.
    Built as a QIcon (not a static asset) since it needs to be re-tinted
    per theme."""
    size = CMD_ICON_SIZE
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    cx, cy = size / 2, size / 2
    painter.setPen(QPen(color, 1.4))
    painter.setBrush(Qt.NoBrush)

    if kind == "hollow_circle":
        painter.drawEllipse(QPointF(cx, cy), 5, 5)
    elif kind == "filled_circle":
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(cx, cy), 5, 5)
    elif kind == "import_arrow":
        painter.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy + 2))
        painter.drawLine(QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2))
        painter.drawLine(QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2))
        painter.drawLine(QPointF(cx - 6, cy + 6), QPointF(cx + 6, cy + 6))
    elif kind == "floppy_disk":
        painter.drawRect(QRectF(cx - 6, cy - 6, 12, 12))
        painter.drawRect(QRectF(cx - 3, cy - 6, 6, 4))
        painter.drawLine(QPointF(cx - 4, cy + 1), QPointF(cx + 4, cy + 1))
    elif kind == "reset_arrow":
        painter.drawArc(QRectF(cx - 6, cy - 6, 12, 12), 10 * 16, 340 * 16)
        painter.drawLine(QPointF(cx - 3, cy - 9), QPointF(cx + 2, cy - 6))
        painter.drawLine(QPointF(cx + 2, cy - 6), QPointF(cx - 2, cy - 3))
    elif kind == "thermometer":
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(cx, cy + 5), 3, 3)
        painter.drawLine(QPointF(cx, cy + 3), QPointF(cx, cy - 6))
        painter.drawLine(QPointF(cx + 2, cy - 4), QPointF(cx + 4, cy - 4))
        painter.drawLine(QPointF(cx + 2, cy - 1), QPointF(cx + 4, cy - 1))

    painter.end()
    return QIcon(pixmap)


def _cmd_btn_style() -> str:
    return (
        f"QPushButton {{ background: {theme_colors.NAVY}; color: {theme_colors.ACCENT_BLUE}; border: 1px solid {theme_colors.NAVY}; "
        f"border-radius: 5px; font-size: 11px; font-weight: 600; padding: 8px 4px; text-align: left; }}"
        f"QPushButton:hover {{ background: {theme_colors.ACCENT_BLUE}; color: {theme_colors.NAVY}; }}"
    )


def _colored_btn(text: str, bg: str, icon_kind: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background: {bg}; border: 1px solid {bg}; border-radius: 5px; "
        f"padding: 8px 4px; font-size: 11px; font-weight: 600; color: white; text-align: left; }}"
        f"QPushButton:hover {{ background: {bg}; }}"
    )
    if icon_kind:
        btn.setIcon(_cmd_icon(icon_kind, QColor("white")))
        btn.setIconSize(QSize(CMD_ICON_SIZE, CMD_ICON_SIZE))
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
        commands_col.setSpacing(4)
        commands_col.addWidget(_section_label("Commands"))

        grid = QGridLayout()
        grid.setSpacing(4)

        shutdown_btn = _colored_btn("Emergency Shutdown", theme_colors.STATUS_ERROR, "hollow_circle")
        shutdown_btn.clicked.connect(self._on_emergency_shutdown)
        grid.addWidget(shutdown_btn, 0, 0)

        activate_btn = _colored_btn("Global Activate", theme_colors.STATUS_OK, "filled_circle")
        activate_btn.clicked.connect(self._on_global_activate)
        grid.addWidget(activate_btn, 0, 1)

        load_btn = QPushButton("Load Config")
        load_btn.setCursor(Qt.PointingHandCursor)
        load_btn.setStyleSheet(_cmd_btn_style())
        load_btn.setIcon(_cmd_icon("import_arrow", QColor(theme_colors.ACCENT_BLUE)))
        load_btn.setIconSize(QSize(CMD_ICON_SIZE, CMD_ICON_SIZE))
        load_btn.clicked.connect(self._on_load_config_clicked)
        grid.addWidget(load_btn, 1, 0)

        save_btn = QPushButton("Save Config")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(_cmd_btn_style())
        save_btn.setIcon(_cmd_icon("floppy_disk", QColor(theme_colors.ACCENT_BLUE)))
        save_btn.setIconSize(QSize(CMD_ICON_SIZE, CMD_ICON_SIZE))
        save_btn.clicked.connect(self._on_save_config_clicked)
        grid.addWidget(save_btn, 1, 1)

        reset_btn = QPushButton("Reset to Default")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setStyleSheet(_cmd_btn_style())
        reset_btn.setIcon(_cmd_icon("reset_arrow", QColor(theme_colors.ACCENT_BLUE)))
        reset_btn.setIconSize(QSize(CMD_ICON_SIZE, CMD_ICON_SIZE))
        reset_btn.clicked.connect(self._on_reset_to_default)
        grid.addWidget(reset_btn, 2, 0)

        highest_temps_btn = QPushButton("Highest Temps")
        highest_temps_btn.setCursor(Qt.PointingHandCursor)
        highest_temps_btn.setStyleSheet(_cmd_btn_style())
        highest_temps_btn.setIcon(_cmd_icon("thermometer", QColor(theme_colors.ACCENT_BLUE)))
        highest_temps_btn.setIconSize(QSize(CMD_ICON_SIZE, CMD_ICON_SIZE))
        highest_temps_btn.clicked.connect(self._on_highest_temps_clicked)
        grid.addWidget(highest_temps_btn, 2, 1)

        commands_col.addLayout(grid)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {theme_colors.TEXT_MUTED}; font-size: 11px;")
        self.status_label.setWordWrap(True)
        commands_col.addWidget(self.status_label)
        commands_col.addStretch(1)

        row.addLayout(commands_col, 1)
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
        mode_col.addWidget(self.mode_icon, 1, alignment=Qt.AlignCenter)
        row.addLayout(mode_col, 1)

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
        from .config_manager_dialog import ConfigManagerDialog

        dialog = ConfigManagerDialog(self, self.app, mode="save")
        if dialog.exec() == QDialog.Accepted:
            self.status_label.setText(f'Config saved as "{dialog.result_name}".')

    def _on_load_config_clicked(self):
        from .config_manager_dialog import ConfigManagerDialog
        from utils.config_slots import load_config_slot

        dialog = ConfigManagerDialog(self, self.app, mode="load")
        if dialog.exec() != QDialog.Accepted:
            return
        saved_states = load_config_slot(self.app.config, dialog.result_name)
        applied = 0
        skipped = 0
        # A config only ever asserts "on" (see save_config_slot()'s own
        # comment on why) - loading one never turns a channel off, so
        # any channel not in the file, or saved off, is simply left
        # exactly as it already is.
        for address, entry in saved_states.items():
            if not entry.get("output_on"):
                continue
            controller = self.app.channels.controllers.get(address)
            if controller is None:
                continue
            level = entry.get("last_level", 0)
            code = LEVEL_TO_HEX[level]
            if code is None:
                continue
            if not self.app.safety.allow_power_on(address):
                skipped += 1
                continue
            if controller.state.data.output_on:
                controller.set_power(code)
            else:
                controller.resume_output(code)
            applied += 1
        status = f"Config loaded: {applied} applied"
        status += f", {skipped} skipped (kill switch tripped)." if skipped else "."
        self.status_label.setText(status)

    def _on_highest_temps_clicked(self):
        from .logs_dialog import LogsDialog
        from utils.sensor_log import read_highest_temp_rows

        rows = read_highest_temp_rows(self.app.config)
        if not rows:
            QMessageBox.information(
                self, "Highest Temp Log",
                "No sensor log entries yet - it's written a few seconds after the first sensor reading.",
            )
            return
        lines = [f"{timestamp}   {peak:.1f}C   BAY{bay + 1}" for timestamp, peak, bay in rows]
        LogsDialog(self, lines, title="Highest Temp Log").exec()


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {theme_colors.TEXT_DARK}; font-size: 11px; font-weight: 700;")
    return lbl


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setStyleSheet(f"color: {theme_colors.BORDER_SUBTLE};")
    return line
