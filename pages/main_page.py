import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QScrollArea, QInputDialog, QSizePolicy, QPushButton, QFileDialog
)
from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtGui import QIcon, QPixmap

from components import (
    ChannelRow, ChannelTableHeader, ConfirmDialog, CloseConfirmDialog, ControlsBar, LogsPanel,
    TitleBar, ResizableContainer, SensorCard, SensorHeatmap,
    BulkActionsBar, KillSwitchBanner,
)
from hooks.use_channels import MAX_CHANNELS
from services.middleware import dll_decode_frame
from styles.theme_colors import BORDER_SUBTLE, ACCENT_BLUE, NAVY, STATUS_ERROR, STATUS_ERROR_DARK
from utils.logging_service import clear_log
from utils.time_format import format_uptime
from utils.app_paths import branding_icon_path, resource_path
from utils.channel_store import load_channel_states, save_channel_states
from state.level_map import LEVEL_TO_HEX

TOP_ROW_HEIGHT = 90
CONTROLS_MIN_WIDTH = 320
SENSOR_MIN_WIDTH = 260
HEATMAP_HEIGHT = 150

BRANDING_ICON_SIZE = 256


class MainWindow(QMainWindow):

    def __init__(self, app_controller):
        super().__init__()
        self.app = app_controller
        self.setWindowTitle("TX Controller")
        self._apply_window_chrome()

        central = ResizableContainer(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(self, "TX Controller", icon=self.windowIcon())
        self.title_bar.close_app_requested.connect(self._on_close_app_clicked)
        self._build_title_bar_actions()
        root.addWidget(self.title_bar)

        self.kill_switch_banner = KillSwitchBanner(self.app)
        root.addWidget(self.kill_switch_banner)

        self.app.uptime_changed.connect(self._on_uptime_changed)
        self._on_uptime_changed(self.app.current_uptime_seconds())

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        root.addWidget(content, 1)

        outer.addLayout(self._build_top_row())
        outer.addWidget(self._build_heatmap())
        self.bulk_actions_bar = BulkActionsBar(self.app)
        outer.addWidget(self.bulk_actions_bar)
        outer.addWidget(self._build_channels_panel(), 1)

        self.setCentralWidget(central)

        self._rows = {}
        self.app.channels.raw_tx.connect(self._on_raw_tx)
        self.app.channels.raw_rx.connect(self._on_raw_rx)

        for address in range(MAX_CHANNELS):
            self._build_row(address)
        self.rows_layout.addStretch(1)

        self._refresh_sensor_ports()
        self.app.sensor.changed.connect(self._on_sensor_changed)
        self._on_sensor_changed()

    def _apply_window_chrome(self):
        self.resize(1040, 780)
        self.setMinimumSize(1000, 700)
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def _build_top_row(self) -> QHBoxLayout:
        # Only 2 boxes now, not 3 - Logs used to sit here at all times
        # despite being secondary/diagnostic info; it still accumulates
        # every TX/RX line in the background (see _on_raw_tx/_on_raw_rx),
        # it's just reached through the "View Logs" button below instead
        # of always taking up a third of this row.
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        self.controls_bar = ControlsBar(min_width=CONTROLS_MIN_WIDTH)
        self.controls_bar.setFixedHeight(TOP_ROW_HEIGHT)
        self.controls_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.controls_bar.query_requested.connect(self._on_query)
        self.controls_bar.clear_log_requested.connect(self._on_clear_log)
        self.controls_bar.load_config_requested.connect(self._on_load_config_clicked)
        self.controls_bar.save_config_requested.connect(self._on_save_config_clicked)
        self.controls_bar.view_logs_requested.connect(lambda: self.logs_panel.open_dialog())
        top_row.addWidget(self.controls_bar, 1, alignment=Qt.AlignTop)

        self.logs_panel = LogsPanel("Logs", icon="list.png", min_width=0, parent=self)

        self.sensor_card = SensorCard(min_width=SENSOR_MIN_WIDTH)
        self.sensor_card.setFixedHeight(TOP_ROW_HEIGHT)
        self.sensor_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.sensor_card.connect_requested.connect(self._on_sensor_connect)
        self.sensor_card.disconnect_requested.connect(self.app.sensor.disconnect)
        self.sensor_card.refresh_requested.connect(self._refresh_sensor_ports)
        top_row.addWidget(self.sensor_card, 1, alignment=Qt.AlignTop)

        return top_row

    def _build_heatmap(self) -> SensorHeatmap:
        heatmap = SensorHeatmap(self.app.sensor)
        heatmap.setFixedHeight(HEATMAP_HEIGHT)
        return heatmap

    def _build_title_bar_actions(self):
        change_logo_btn = QPushButton("Change Logo…")
        change_logo_btn.setCursor(Qt.PointingHandCursor)
        change_logo_btn.setToolTip("Pick a custom window/taskbar icon - applies immediately, no restart")
        change_logo_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {ACCENT_BLUE}; border: 1px solid {ACCENT_BLUE}; "
            f"border-radius: 4px; font-size: 10px; padding: 3px 8px; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE}; color: {NAVY}; }}"
        )
        change_logo_btn.clicked.connect(self._on_change_logo_clicked)
        self.title_bar.add_action_widget(change_logo_btn)

        reset_logo_btn = QPushButton("Reset")
        reset_logo_btn.setCursor(Qt.PointingHandCursor)
        reset_logo_btn.setToolTip("Restore the default icon")
        reset_logo_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {ACCENT_BLUE}; border: 1px solid {ACCENT_BLUE}; "
            f"border-radius: 4px; font-size: 10px; padding: 3px 8px; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE}; color: {NAVY}; }}"
        )
        reset_logo_btn.clicked.connect(self._on_reset_logo_clicked)
        self.title_bar.add_action_widget(reset_logo_btn)

        # Always available, not gated on a trip already being active -
        # for testing the interlock without needing the amplifier to
        # actually reach KILL_SWITCH_THRESHOLD_C.
        force_trip_btn = QPushButton("Force Trip")
        force_trip_btn.setCursor(Qt.PointingHandCursor)
        force_trip_btn.setToolTip("Manually trip the kill switch - forces every channel off")
        force_trip_btn.setStyleSheet(
            f"QPushButton {{ background: {STATUS_ERROR}; color: white; border: 1px solid {STATUS_ERROR}; "
            f"border-radius: 4px; font-size: 10px; font-weight: 600; padding: 3px 8px; }}"
            f"QPushButton:hover {{ background: {STATUS_ERROR_DARK}; }}"
        )
        force_trip_btn.clicked.connect(self._on_force_trip_clicked)
        self.title_bar.add_action_widget(force_trip_btn)

    def _build_channels_panel(self) -> QFrame:
        # One bordered panel - a fixed header row (ChannelTableHeader)
        # pinned above a scrollable body of ChannelRow widgets, standard
        # table layout - replacing the old 4-per-row card grid, which at
        # 16 channels needed scrolling to see everything at once and
        # gave each channel a lot of vertical chrome (icon, header,
        # border) for not much information. A row is ~40px; all 16 fit
        # on screen together without scrolling on the default window size.
        panel = QFrame()
        panel.setObjectName("ChannelsPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setStyleSheet(
            f"#ChannelsPanel {{ background: #FFFFFF; border: 1px solid {BORDER_SUBTLE}; "
            f"border-radius: 10px; }}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        panel_layout.addWidget(ChannelTableHeader())

        scroll = QScrollArea()
        scroll.setObjectName("ChannelsScroll")
        scroll.setStyleSheet(f"""
            #ChannelsScroll {{ border: none; background: #FFFFFF; border-radius: 0 0 10px 10px; }}
            #ChannelsScroll QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 0px;
            }}
            #ChannelsScroll QScrollBar::handle:vertical {{
                background: {BORDER_SUBTLE};
                border-radius: 5px;
                min-height: 24px;
            }}
            #ChannelsScroll QScrollBar::handle:vertical:hover {{
                background: {ACCENT_BLUE};
            }}
            #ChannelsScroll QScrollBar::add-line:vertical,
            #ChannelsScroll QScrollBar::sub-line:vertical {{
                height: 0px;
                background: transparent;
                border: none;
            }}
            #ChannelsScroll QScrollBar::add-page:vertical,
            #ChannelsScroll QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)
        scroll.viewport().setStyleSheet("background: transparent;")
        scroll.setWidgetResizable(True)
        self.channels_scroll = scroll

        rows_container = QWidget()
        self.rows_layout = QVBoxLayout(rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        scroll.setWidget(rows_container)
        panel_layout.addWidget(scroll, 1)

        return panel

    def _on_uptime_changed(self, seconds: int):
        self.title_bar.set_uptime(f"Uptime {format_uptime(seconds)}")

    def _on_query(self):
        address, ok = QInputDialog.getInt(self, "Query", "Address to send to:", 1, 0, 199)
        if not ok:
            return
        choice, ok = QInputDialog.getItem(self, "Query", "Output:", ["ON", "OFF"], editable=False)
        if not ok:
            return
        self.controls_bar.set_status(f"Querying {choice} to address {address}…")
        self.app.channels.brute_force_query(address, on=(choice == "ON"))

    def _on_clear_log(self):
        clear_log(self.app.logger)
        self.logs_panel.clear()
        self.controls_bar.set_status("Log cleared.")

    def _on_save_config_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config", "channels.ini", "Config files (*.ini)"
        )
        if not path:
            return
        save_channel_states(self.app.channels.states, path)
        self.controls_bar.set_status("Config saved.")

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
        self.controls_bar.set_status(status)

    def _refresh_sensor_ports(self):
        from hooks.use_sensor import SensorController
        ports = SensorController.list_ports()
        saved = self.app.config.get("sensor_port")
        self.sensor_card.set_ports(ports, saved)

    def _on_sensor_connect(self, port_name: str):
        if not port_name or port_name == "No ports found":
            return
        if self.app.sensor.connect(port_name):
            self.app.config.set("sensor_port", port_name)
            self.app.config.save()

    def _on_sensor_changed(self):
        self.sensor_card.set_connected(self.app.sensor.connected)
        avg = self.app.sensor.average_temperature()
        bay_count = len(self.app.sensor.units)
        reading_count = sum(1 for u in self.app.sensor.units if u.has_reading)
        self.sensor_card.set_average_temperature(avg, bay_count, reading_count)

    def _on_force_trip_clicked(self):
        confirmed = ConfirmDialog.ask(
            self,
            "Force every channel off immediately?",
            "This trips the kill switch manually, same as an automatic overtemp "
            "trip - every channel stays off until reset.",
            confirm_text="Force Trip",
            cancel_text="Cancel",
            danger=True,
        )
        if confirmed:
            self.app.safety.manual_trip_all()

    def _on_change_logo_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a logo image", "", "Images (*.png *.jpg *.jpeg *.bmp *.ico)"
        )
        if not path:
            return
        source = QPixmap(path)
        if source.isNull():
            return
        resized = source.scaled(
            BRANDING_ICON_SIZE, BRANDING_ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        dest = branding_icon_path()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        resized.save(dest, "PNG")
        self._apply_app_icon()

    def _on_reset_logo_clicked(self):
        dest = branding_icon_path()
        if os.path.exists(dest):
            os.remove(dest)
        self._apply_app_icon()

    def _apply_app_icon(self):
        from PySide6.QtWidgets import QApplication
        path = branding_icon_path()
        if not os.path.exists(path):
            path = resource_path("assets", "icons", "app_icon.png")
        if not os.path.exists(path):
            return
        icon = QIcon(path)
        QApplication.instance().setWindowIcon(icon)
        self.setWindowIcon(icon)
        self.title_bar.set_icon(icon)

    def _on_raw_tx(self, address: int, data: bytes):
        encoded_value, _ = dll_decode_frame(data)
        main_display = encoded_value if encoded_value is not None else "[middleware unavailable]"
        self.logs_panel.append_line(f"TX CH{address:02d}: {main_display}")

    def _on_raw_rx(self, address: int, data: bytes):
        encoded_value, _ = dll_decode_frame(data)
        main_display = encoded_value if encoded_value is not None else "[middleware unavailable]"
        self.logs_panel.append_line(f"RX CH{address:02d}: {main_display}")

    def _build_row(self, address: int):
        controller = self.app.channels.get_controller(address)
        state = self.app.channels.get_state(address)
        row = ChannelRow(controller, state, self.app.safety, self.app.selection, row_index=address)
        self._rows[address] = row
        self.rows_layout.addWidget(row)

    def closeEvent(self, event):
        self.app.shutdown()
        event.accept()

    def _on_close_app_clicked(self):
        choice = CloseConfirmDialog.ask(self)
        if choice is None:
            return
        if choice == "turn_off":
            self._turn_off_all_and_close()
        else:
            self.close()

    def _turn_off_all_and_close(self):
        # Actually waits for every channel's OFF send to settle (busy_changed
        # -> False) before closing - firing turn_output_off() and quitting
        # immediately would race AppController.shutdown()'s
        # channels.shutdown(), which cancels whatever's still pending.
        pending = set(self.app.channels.controllers.keys())
        loop = QEventLoop()

        def _on_busy_changed(address, busy):
            if not busy:
                pending.discard(address)
                if not pending:
                    loop.quit()

        connections = []
        for address, controller in self.app.channels.controllers.items():
            slot = lambda busy, addr=address: _on_busy_changed(addr, busy)
            controller.busy_changed.connect(slot)
            connections.append((controller, slot))
            controller.turn_output_off()

        if pending:
            loop.exec()

        for controller, slot in connections:
            controller.busy_changed.disconnect(slot)

        self.close()
