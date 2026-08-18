from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QInputDialog, QApplication, QSizePolicy
)
from PySide6.QtCore import Qt, QEvent

from components import (
    ChannelCard, ConfirmDialog, ControlsBar, LogsPanel,
    TitleBar, ResizableContainer,
)
from hooks.use_channels import MAX_CHANNELS
from services.middleware import dll_decode_frame
from services.protocol.packet_parser import describe_command
from services.team_vocab import encode_team_tokens
from styles.theme_colors import BORDER_SUBTLE, ACCENT_BLUE
from utils.logging_service import clear_log

TOP_ROW_HEIGHT = 90
CONTROLS_MIN_WIDTH = 260
LOGS_MIN_WIDTH = 260
DEV_LOGS_MIN_WIDTH = 200

DEV_MODE_SEQUENCE = ["`", "d", "e", "v"]
CHANNELS_PER_ROW = 4


class MainWindow(QMainWindow):

    def __init__(self, app_controller):
        super().__init__()
        self.app = app_controller
        self.setWindowTitle("Noise Controller")
        self._apply_window_chrome()

        central = ResizableContainer(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(self, "Noise Controller", icon=self.windowIcon())
        self.title_bar.close_app_requested.connect(self._on_close_app_clicked)
        root.addWidget(self.title_bar)

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        root.addWidget(content, 1)

        outer.addLayout(self._build_top_row())
        outer.addWidget(self._build_channels_scroll(), 1)

        self.setCentralWidget(central)

        self._cards = {}
        self._armed_card = None
        self.app.channels.raw_tx.connect(self._on_raw_tx)
        self.app.channels.raw_rx.connect(self._on_raw_rx)

        for address in range(MAX_CHANNELS):
            self._build_card(address)

        self.dev_mode = False
        self._dev_key_buffer = []

        QApplication.instance().installEventFilter(self)

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

        self.logs_panel = LogsPanel("Logs", icon="fa5s.list", min_width=LOGS_MIN_WIDTH)
        self.logs_panel.setFixedHeight(TOP_ROW_HEIGHT)
        self.logs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        top_row.addWidget(self.logs_panel, 4, alignment=Qt.AlignTop)

        self.dev_logs_panel = LogsPanel("Dev Logs", icon="fa5s.code", min_width=DEV_LOGS_MIN_WIDTH)
        self.dev_logs_panel.setFixedHeight(TOP_ROW_HEIGHT)
        self.dev_logs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.dev_logs_panel.setVisible(False)
        top_row.addWidget(self.dev_logs_panel, 3, alignment=Qt.AlignTop)

        return top_row

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

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.MouseButtonPress
            and self._armed_card is not None
            and isinstance(obj, QWidget)
            and QApplication.activePopupWidget() is None
        ):
            if not (obj is self._armed_card or self._armed_card.isAncestorOf(obj)):
                self._armed_card.disarm()
                self._armed_card = None

        if event.type() == QEvent.KeyPress and obj is self:
            self._track_dev_mode_key(event)

        return super().eventFilter(obj, event)

    def _track_dev_mode_key(self, event):
        if event.isAutoRepeat():
            return

        if event.key() == Qt.Key_QuoteLeft:
            char = "`"
        elif event.text():
            char = event.text().lower()
        else:
            return

        self._dev_key_buffer.append(char)
        self._dev_key_buffer = self._dev_key_buffer[-len(DEV_MODE_SEQUENCE):]
        if self._dev_key_buffer == DEV_MODE_SEQUENCE:
            self._dev_key_buffer = []
            self.dev_mode = not self.dev_mode
            self.title_bar.set_dev_mode(self.dev_mode)
            self.dev_logs_panel.setVisible(self.dev_mode)

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
        self.dev_logs_panel.clear()
        self.controls_bar.set_status("Log cleared.")

    def _on_raw_tx(self, address: int, data: bytes):
        decoded = describe_command(data)
        encoded_value, encoded_error = dll_decode_frame(data)
        main_display = encoded_value if encoded_value is not None else "[middleware unavailable]"
        self.logs_panel.append_line(f"TX CH{address:02d}: {main_display}")
        if self.dev_mode:
            dev_display = encoded_value if encoded_value is not None else f"[middleware unavailable: {encoded_error}]"
            team_tokens = encode_team_tokens(data)
            self.dev_logs_panel.append_line(f"CH{address:02d}: {decoded}")
            self.dev_logs_panel.append_line(f"ENC: {dev_display}")
            self.dev_logs_panel.append_line(f"TOK: {team_tokens}")

    def _on_raw_rx(self, address: int, data: bytes):
        encoded_value, encoded_error = dll_decode_frame(data)
        main_display = encoded_value if encoded_value is not None else "[middleware unavailable]"
        self.logs_panel.append_line(f"RX CH{address:02d}: {main_display}")
        if self.dev_mode:
            dev_display = encoded_value if encoded_value is not None else f"[middleware unavailable: {encoded_error}]"
            self.dev_logs_panel.append_line(f"RX ENC CH{address:02d}: {dev_display}")

    def _build_card(self, address: int):
        controller = self.app.channels.get_controller(address)
        state = self.app.channels.get_state(address)
        card = ChannelCard(controller, state)
        card.armed.connect(lambda c=card: self._on_card_armed(c))
        self._cards[address] = card
        self._reflow_grid()

    def _on_card_armed(self, card: ChannelCard):
        if self._armed_card is not None and self._armed_card is not card:
            self._armed_card.disarm()
        self._armed_card = card

    def _reflow_grid(self):
        if not self._cards:
            return
        for index, address in enumerate(sorted(self._cards)):
            row, col = divmod(index, CHANNELS_PER_ROW)
            self.grid.addWidget(self._cards[address], row, col)
        for col in range(CHANNELS_PER_ROW):
            self.grid.setColumnStretch(col, 1)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
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
