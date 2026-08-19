from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QInputDialog, QSizePolicy
)
from PySide6.QtCore import Qt

from components import ChannelCard, ConfirmDialog, ControlsBar, LogsPanel
from hooks.use_channels import MAX_CHANNELS
from services.middleware import dll_decode_frame
from utils.logging_service import clear_log

TOP_ROW_HEIGHT = 90
CONTROLS_MIN_WIDTH = 260
LOGS_MIN_WIDTH = 260

CHANNELS_PER_ROW = 4


class MainWindow(QMainWindow):

    def __init__(self, app_controller):
        super().__init__()
        self.app = app_controller
        self.setWindowTitle("TX Controller")
        self.resize(1040, 780)
        self.setMinimumSize(1000, 700)

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        outer.addLayout(self._build_top_row())
        outer.addWidget(self._build_channels_scroll(), 1)

        self.setCentralWidget(content)

        self._cards = {}
        self.app.channels.raw_tx.connect(self._on_raw_tx)
        self.app.channels.raw_rx.connect(self._on_raw_rx)

        for address in range(MAX_CHANNELS):
            self._build_card(address)

    def _build_top_row(self) -> QHBoxLayout:
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        self.controls_bar = ControlsBar(min_width=CONTROLS_MIN_WIDTH)
        self.controls_bar.setFixedHeight(TOP_ROW_HEIGHT)
        self.controls_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.controls_bar.query_requested.connect(self._on_query)
        self.controls_bar.clear_log_requested.connect(self._on_clear_log)
        top_row.addWidget(self.controls_bar, 3, alignment=Qt.AlignTop)

        self.logs_panel = LogsPanel("Logs", icon="fa5s.list", min_width=LOGS_MIN_WIDTH)
        self.logs_panel.setFixedHeight(TOP_ROW_HEIGHT)
        self.logs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        top_row.addWidget(self.logs_panel, 4, alignment=Qt.AlignTop)

        return top_row

    def _build_channels_scroll(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.channels_scroll = scroll
        grid_container = QWidget()
        self.grid = QGridLayout(grid_container)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll.setWidget(grid_container)
        return scroll

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
        card = ChannelCard(controller, state)
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
            event.ignore()
            return
        self.app.shutdown()
        event.accept()
