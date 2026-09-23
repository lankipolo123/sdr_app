import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QInputDialog, QSizePolicy, QPushButton, QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

from components import (
    ChannelCard, ConfirmDialog, ControlsBar, LogsPanel,
    TitleBar, ResizableContainer, SensorCard, SensorHeatmap,
    BulkActionsBar, KillSwitchBanner,
)
from hooks.use_channels import MAX_CHANNELS
from services.middleware import dll_decode_frame
from styles.theme_colors import BORDER_SUBTLE, ACCENT_BLUE, NAVY, STATUS_ERROR, STATUS_ERROR_DARK
from utils.logging_service import clear_log
from utils.time_format import format_uptime
from utils.app_paths import branding_icon_path, resource_path

TOP_ROW_HEIGHT = 90
CONTROLS_MIN_WIDTH = 220
LOGS_MIN_WIDTH = 220
SENSOR_MIN_WIDTH = 220
HEATMAP_HEIGHT = 150

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

        outer.addLayout(self._build_top_row())
        outer.addWidget(self._build_heatmap())
        self.bulk_actions_bar = BulkActionsBar(self.app)
        outer.addWidget(self.bulk_actions_bar)
        outer.addWidget(self._build_channels_scroll(), 1)

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
        self.resize(1040, 780)
        self.setMinimumSize(1000, 700)
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def _build_top_row(self) -> QHBoxLayout:
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        self.controls_bar = ControlsBar(min_width=CONTROLS_MIN_WIDTH)
        self.controls_bar.setFixedHeight(TOP_ROW_HEIGHT)
        self.controls_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.controls_bar.query_requested.connect(self._on_query)
        self.controls_bar.clear_log_requested.connect(self._on_clear_log)
        top_row.addWidget(self.controls_bar, 3, alignment=Qt.AlignTop)

        self.logs_panel = LogsPanel("Logs", icon="list.png", min_width=LOGS_MIN_WIDTH)
        self.logs_panel.setFixedHeight(TOP_ROW_HEIGHT)
        self.logs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        top_row.addWidget(self.logs_panel, 4, alignment=Qt.AlignTop)

        self.sensor_card = SensorCard(min_width=SENSOR_MIN_WIDTH)
        self.sensor_card.setFixedHeight(TOP_ROW_HEIGHT)
        self.sensor_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.sensor_card.connect_requested.connect(self._on_sensor_connect)
        self.sensor_card.disconnect_requested.connect(self.app.sensor.disconnect)
        self.sensor_card.refresh_requested.connect(self._refresh_sensor_ports)
        top_row.addWidget(self.sensor_card, 3, alignment=Qt.AlignTop)

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
        card = ChannelCard(controller, state, self.app.cw_auth, self.app.safety, self.app.selection)
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
        confirmed = ConfirmDialog.ask(
            self,
            "Close App",
            "Close the app? Channel power states are left as they are - "
            "this does not turn anything off.",
            confirm_text="Close",
            cancel_text="Cancel",
            danger=True,
        )
        if not confirmed:
            return
        self.close()
