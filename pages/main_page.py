import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QInputDialog, QSizePolicy, QPushButton, QFileDialog
)
from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtGui import QIcon, QPixmap

from components import (
    ChannelCard, ConfirmDialog, CloseConfirmDialog, ControlsBar, LogsPanel,
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

# Layout mirrors sdr_c's actual window (Connection/Sensors + heatmap +
# Bulk Actions in one header band; a narrow sidebar - Activity Log there
# - beside the channel grid; Commands as its own full-width panel below
# the grid, not above it). Same panels sdr_app already had, just placed
# the way the C rewrite places them instead of everything stacked
# full-width in one column.
HEADER_ROW_HEIGHT = 150
SENSOR_MIN_WIDTH = 260
BULK_ACTIONS_MIN_WIDTH = 320
SIDEBAR_WIDTH = 260

CHANNELS_PER_ROW = 4
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

        outer.addLayout(self._build_header_row())
        outer.addLayout(self._build_body_row(), 1)

        self.controls_bar = ControlsBar(min_width=0)
        self.controls_bar.query_requested.connect(self._on_query)
        self.controls_bar.clear_log_requested.connect(self._on_clear_log)
        self.controls_bar.load_config_requested.connect(self._on_load_config_clicked)
        self.controls_bar.save_config_requested.connect(self._on_save_config_clicked)
        outer.addWidget(self.controls_bar)

        self.setCentralWidget(central)

        self._cards = {}
        self.app.channels.raw_tx.connect(self._on_raw_tx)
        self.app.channels.raw_rx.connect(self._on_raw_rx)

        for address in range(MAX_CHANNELS):
            self._build_card(address)

        self._refresh_sensor_ports()
        self.app.sensor.changed.connect(self._on_sensor_changed)
        self._on_sensor_changed()

    def _apply_window_chrome(self):
        self.resize(1300, 860)
        self.setMinimumSize(1100, 760)
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def _build_header_row(self) -> QHBoxLayout:
        # Connection/sensor status, the heatmap, and Bulk Actions all in
        # one band - direct match for sdr_c's header (Connection &
        # Settings + Ambient Temperature + heatmap + Bulk Actions all
        # sitting side by side above the grid).
        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        self.sensor_card = SensorCard(min_width=SENSOR_MIN_WIDTH)
        self.sensor_card.setFixedHeight(HEADER_ROW_HEIGHT)
        self.sensor_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.sensor_card.connect_requested.connect(self._on_sensor_connect)
        self.sensor_card.disconnect_requested.connect(self.app.sensor.disconnect)
        self.sensor_card.refresh_requested.connect(self._refresh_sensor_ports)
        header_row.addWidget(self.sensor_card, 0, alignment=Qt.AlignTop)

        heatmap = SensorHeatmap(self.app.sensor)
        heatmap.setFixedHeight(HEADER_ROW_HEIGHT)
        header_row.addWidget(heatmap, 1, alignment=Qt.AlignTop)

        self.bulk_actions_bar = BulkActionsBar(self.app)
        self.bulk_actions_bar.setFixedHeight(HEADER_ROW_HEIGHT)
        self.bulk_actions_bar.setMinimumWidth(BULK_ACTIONS_MIN_WIDTH)
        self.bulk_actions_bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        header_row.addWidget(self.bulk_actions_bar, 0, alignment=Qt.AlignTop)

        return header_row

    def _build_body_row(self) -> QHBoxLayout:
        # Narrow sidebar (Activity Log) beside the channel grid, same
        # split sdr_c's Spectrum/Activity Log sidebar makes against its
        # own channel grid - not a full-width strip above everything.
        body_row = QHBoxLayout()
        body_row.setSpacing(16)

        self.logs_panel = LogsPanel("Logs", icon="list.png", min_width=SIDEBAR_WIDTH)
        self.logs_panel.setFixedWidth(SIDEBAR_WIDTH)
        self.logs_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        body_row.addWidget(self.logs_panel, 0)

        body_row.addWidget(self._build_channels_scroll(), 1)

        return body_row

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

    def _build_channels_scroll(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("ChannelsScroll")
        scroll.setStyleSheet(f"""
            #ChannelsScroll {{ border: none; background: #FFFFFF; }}
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
        grid_container = QWidget()
        self.grid = QGridLayout(grid_container)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll.setWidget(grid_container)
        return scroll

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

    def _build_card(self, address: int):
        controller = self.app.channels.get_controller(address)
        state = self.app.channels.get_state(address)
        card = ChannelCard(controller, state, self.app.safety, self.app.selection)
        self._cards[address] = card
        self._reflow_grid()

    def _reflow_grid(self):
        if not self._cards:
            return
        for index, address in enumerate(sorted(self._cards)):
            row, col = divmod(index, CHANNELS_PER_ROW)
            self.grid.addWidget(self._cards[address], row, col)
        for col in range(CHANNELS_PER_ROW):
            self.grid.setColumnStretch(col, 1)

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
