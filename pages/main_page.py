from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QScrollArea, QPushButton
)
from PySide6.QtCore import Qt

from components import (
    ConnectionBar, ChannelCard, EmergencyStopButton, ConfirmDialog,
    TitleBar, ResizableContainer,
)
from styles.theme_colors import TEXT_MUTED, BORDER_SUBTLE

MAX_COLUMNS = 4


class MainWindow(QMainWindow):
    """One screen: a connection bar up top, then a grid of per-channel
    cards. No Dashboard/Device Control/Communication pages, no sidebar,
    no Module Address field anywhere."""

    def __init__(self, app_controller):
        super().__init__()
        self.app = app_controller
        self.setWindowTitle("SDR App")
        self.resize(900, 640)
        # No native OS title bar - a custom one (styled to match the rest
        # of the app) replaces it entirely; see components/window_chrome.py
        # for the drag-to-move / edge-resize logic that replicates.
        self.setWindowFlag(Qt.FramelessWindowHint)
        # Makes the top-level window itself transparent so only
        # ResizableContainer's rounded card is visible - without this the
        # window would still be a plain square (or show Windows' own
        # square frame/shadow) behind the rounding.
        self.setAttribute(Qt.WA_TranslucentBackground)

        central = ResizableContainer(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(self, "SDR App", icon=self.windowIcon())
        self.title_bar.close_app_requested.connect(self._on_close_app_clicked)
        root.addWidget(self.title_bar)

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        root.addWidget(content, 1)

        self.connection_bar = ConnectionBar(self.app.connection, self.app.config)
        outer.addWidget(self.connection_bar, alignment=Qt.AlignLeft)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Not connected.")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED};")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.setToolTip("Scan again for newly-connected channels")
        self.rescan_btn.clicked.connect(self._on_rescan)
        status_row.addWidget(self.rescan_btn)
        outer.addLayout(status_row)

        bulk_row = QHBoxLayout()
        bulk_caption = QLabel("Set all channels:")
        bulk_caption.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        bulk_row.addWidget(bulk_caption)
        self.bulk_buttons = []
        for level in range(4):
            btn = QPushButton(f"L{level}")
            btn.setFixedWidth(40)
            btn.setStyleSheet(f"QPushButton {{ border: 1px solid {BORDER_SUBTLE}; border-radius: 5px; }}")
            btn.clicked.connect(lambda _checked, lv=level: self.app.channels.set_all_level(lv))
            bulk_row.addWidget(btn)
            self.bulk_buttons.append(btn)
        bulk_row.addStretch()
        outer.addLayout(bulk_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        grid_container = QWidget()
        self.grid = QGridLayout(grid_container)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll.setWidget(grid_container)
        outer.addWidget(scroll)

        self.stop_btn = EmergencyStopButton()
        self.stop_btn.clicked.connect(self._on_emergency_stop)
        outer.addWidget(self.stop_btn)

        self.setCentralWidget(central)

        self._cards = {}
        self.app.channels.channel_added.connect(self._on_channel_added)
        self.app.channels.discovery_progress.connect(self._on_discovery_progress)
        self.app.channels.discovery_finished.connect(self._on_discovery_finished)
        self.app.connection.connected_changed.connect(self._on_connected_changed)

    def _on_connected_changed(self, connected: bool):
        if connected:
            self.status_label.setText("Scanning for connected channels…")
            self.app.channels.start_discovery()
        else:
            self.status_label.setText("Not connected.")

    def _on_discovery_progress(self, current: int, total: int):
        self.status_label.setText(f"Scanning… checked address {current}/{total}")

    def _on_discovery_finished(self):
        count = len(self._cards)
        self.status_label.setText(
            f"{count} channel(s) found." if count else
            "No channels responded. Check wiring and power."
        )

    def _on_rescan(self):
        if not self.app.connection.is_connected():
            self.status_label.setText("Connect first before rescanning.")
            return
        self.status_label.setText("Rescanning… checking for new channels")
        self.app.channels.start_discovery()

    def _on_channel_added(self, address: int):
        controller = self.app.channels.get_controller(address)
        state = self.app.channels.get_state(address)
        card = ChannelCard(controller, state)
        self._cards[address] = card
        index = len(self._cards) - 1
        self.grid.addWidget(card, index // MAX_COLUMNS, index % MAX_COLUMNS)

    def closeEvent(self, event):
        self.app.shutdown()
        event.accept()

    def _on_emergency_stop(self):
        confirmed = ConfirmDialog.ask(
            self,
            "Emergency Stop",
            "Immediately turn off every channel's output?",
            confirm_text="Turn Off",
            cancel_text="Cancel",
            danger=True,
        )
        if not confirmed:
            return
        self.app.channels.turn_off_all()

    def _on_close_app_clicked(self):
        confirmed = ConfirmDialog.ask(
            self,
            "Close App",
            "Close the app? Channel power states are left as they are - "
            "this does not turn anything off.",
            confirm_text="Close",
            cancel_text="Cancel",
        )
        if not confirmed:
            return
        self.close()
