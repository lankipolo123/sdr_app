from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QFileDialog
from PySide6.QtCore import Qt, Signal

from .card import Card
from styles import theme_colors
from styles.thermal_color import temp_band_color
from utils.channel_store import load_channel_states, save_channel_states
from state.level_map import LEVEL_TO_HEX

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


def _pill() -> QLabel:
    pill = QLabel("-")
    pill.setAlignment(Qt.AlignCenter)
    pill.setFixedHeight(30)
    pill.setStyleSheet(
        f"QLabel {{ background: {theme_colors.FIELD_BG}; color: {theme_colors.TEXT_MUTED}; border-radius: 6px; "
        f"font-size: 13px; font-weight: 700; }}"
    )
    return pill


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
        self.avg_pill = _pill()
        avg_col.addWidget(self.avg_pill)
        avg_col.addStretch(1)
        row.addLayout(avg_col, 1)

        row.addWidget(_divider())

        # ---- Highest Temp Today ----
        highest_col = QVBoxLayout()
        highest_col.setSpacing(6)
        highest_col.addWidget(_section_label("Highest Temp Today"))
        self.highest_pill = _pill()
        highest_col.addWidget(self.highest_pill)
        highest_col.addStretch(1)
        row.addLayout(highest_col, 1)

        row.addWidget(_divider())

        # ---- Mode ----
        mode_col = QVBoxLayout()
        mode_col.setSpacing(6)
        mode_col.addWidget(_section_label("Mode"))
        self.mode_btn = QPushButton()
        self.mode_btn.setCursor(Qt.PointingHandCursor)
        self.mode_btn.setStyleSheet(_cmd_btn_style())
        self.mode_btn.clicked.connect(self._on_mode_toggle_clicked)
        mode_col.addWidget(self.mode_btn)
        mode_col.addStretch(1)
        row.addLayout(mode_col, 1)

        self.body_layout.addLayout(row)

        self.app.sensor.changed.connect(self.refresh_temps)
        self.refresh_temps()
        self._refresh_mode_btn()

    def _refresh_mode_btn(self):
        # Shows the mode you'd SWITCH TO, same label convention as
        # sdr_c's own g_mode_toggle_btn (main.c): "Dark Mode" while
        # light, "Light Mode" while dark.
        self.mode_btn.setText("Light Mode" if not theme_colors.is_light_mode() else "Dark Mode")

    def _on_mode_toggle_clicked(self):
        self.theme_toggle_requested.emit()

    def refresh_temps(self):
        avg = self.app.sensor.average_temperature()
        if avg is None:
            self.avg_pill.setText("-")
            self.avg_pill.setStyleSheet(
                f"QLabel {{ background: {theme_colors.FIELD_BG}; color: {theme_colors.TEXT_MUTED}; border-radius: 6px; "
                f"font-size: 13px; font-weight: 700; }}"
            )
        else:
            r, g, b = temp_band_color(avg)
            self.avg_pill.setText(f"{avg:.1f}°C")
            self.avg_pill.setStyleSheet(
                f"QLabel {{ background: {theme_colors.FIELD_BG}; color: rgb({r},{g},{b}); border-radius: 6px; "
                f"font-size: 13px; font-weight: 700; }}"
            )

        highest = self.app.sensor.highest_temp_today_c
        if highest is None:
            self.highest_pill.setText("-")
            self.highest_pill.setStyleSheet(
                f"QLabel {{ background: {theme_colors.FIELD_BG}; color: {theme_colors.TEXT_MUTED}; border-radius: 6px; "
                f"font-size: 13px; font-weight: 700; }}"
            )
        else:
            r, g, b = temp_band_color(highest)
            self.highest_pill.setText(f"{highest:.1f}°C")
            self.highest_pill.setStyleSheet(
                f"QLabel {{ background: {theme_colors.FIELD_BG}; color: rgb({r},{g},{b}); border-radius: 6px; "
                f"font-size: 13px; font-weight: 700; }}"
            )

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
