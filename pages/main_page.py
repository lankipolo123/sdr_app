from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QScrollArea, QPushButton
)
from PySide6.QtCore import Qt, QTimer

from components import (
    ConnectionBar, ChannelCard, EmergencyStopButton, ConfirmDialog, ManualAddDialog,
    TitleBar, ResizableContainer, make_card,
)
from hooks.use_connection import ConnectionController
from styles.theme_colors import (
    TEXT_MUTED, TEXT_DARK, BORDER_SUBTLE, WARNING_TEXT, WARNING_BG, WARNING_BORDER,
    ACCENT_BLUE, NAVY,
)
from state.level_map import LEVEL_LABELS, LEVEL_LABELS_FULL
from utils.logging_service import clear_log

WARNING_DISPLAY_MS = 6000

MAX_COLUMNS = 4

# Connection / Controls / Emergency all share this exact size so the top
# row reads as three equal panels, not mismatched widgets.
TOP_CARD_SIZE = (320, 120)


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
        # for the drag-to-move logic that replicates.
        self.setWindowFlag(Qt.FramelessWindowHint)
        # Windows still tries to draw its own drop shadow around a
        # frameless window using its actual rectangular bounds, which
        # doesn't line up with our rounded-corner mask (ResizableContainer)
        # - shows up as a dark sliver near a corner that doesn't match the
        # visible content. Telling it not to draw one at all avoids that.
        self.setWindowFlag(Qt.NoDropShadowWindowHint)
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

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        self.connection_bar = ConnectionBar(self.app.channels)
        self.connection_bar.setFixedSize(*TOP_CARD_SIZE)
        top_row.addWidget(self.connection_bar, alignment=Qt.AlignTop)

        controls_card = make_card("Controls", icon="fa5s.sliders-h")
        controls_card.setFixedSize(*TOP_CARD_SIZE)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Not scanned yet.")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        self.manual_ask_btn = QPushButton("+ Addr")
        self.manual_ask_btn.setToolTip("Ask one specific address directly - no broadcast")
        self.manual_ask_btn.setStyleSheet(f"QPushButton {{ border: 1px solid {BORDER_SUBTLE}; border-radius: 5px; }}")
        self.manual_ask_btn.clicked.connect(self._on_manual_ask)
        status_row.addWidget(self.manual_ask_btn)
        self.rescan_btn = QPushButton("Scan")
        self.rescan_btn.setToolTip("Scan for connected channels")
        self.rescan_btn.clicked.connect(self._on_rescan)
        status_row.addWidget(self.rescan_btn)
        controls_card.body_layout.addLayout(status_row)

        bulk_row = QHBoxLayout()
        bulk_caption = QLabel("Set all:")
        bulk_caption.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        bulk_row.addWidget(bulk_caption)
        self.bulk_buttons = []
        for level in range(4):
            btn = QPushButton(LEVEL_LABELS[level])
            btn.setToolTip(f"L{level} - {LEVEL_LABELS_FULL[level]}")
            btn.setFixedWidth(48)
            btn.setStyleSheet(f"QPushButton {{ border: 1px solid {BORDER_SUBTLE}; border-radius: 5px; }}")
            btn.clicked.connect(lambda _checked, lv=level: self.app.channels.set_all_level(lv))
            bulk_row.addWidget(btn)
            self.bulk_buttons.append(btn)
        bulk_row.addStretch()
        controls_card.body_layout.addLayout(bulk_row)

        top_row.addWidget(controls_card, alignment=Qt.AlignTop)

        self.stop_btn = EmergencyStopButton(icon_size=28, font_size=16)
        self.stop_btn.setFixedSize(*TOP_CARD_SIZE)
        self.stop_btn.clicked.connect(self._on_emergency_stop)
        top_row.addWidget(self.stop_btn, alignment=Qt.AlignTop)

        top_row.addStretch()
        outer.addLayout(top_row)

        self._warning_timer = QTimer(self)
        self._warning_timer.setSingleShot(True)
        self._warning_timer.timeout.connect(lambda: self.warning_label.setVisible(False))

        channels_label = QLabel("Channels")
        channels_label.setStyleSheet(f"color: {TEXT_DARK}; font-weight: 700; font-size: 12px;")
        outer.addWidget(channels_label)

        # Matches Card's own border weight/radius+color exactly (2px
        # solid BORDER_SUBTLE, 10px radius) so this reads as the same
        # kind of section as Connection/Controls/Emergency, not a
        # plain unstyled scroll area. Scoped to #ChannelsScroll so it
        # doesn't cascade onto the cards placed inside it.
        scroll = QScrollArea()
        scroll.setObjectName("ChannelsScroll")
        scroll.setStyleSheet(
            f"#ChannelsScroll {{ border: 2px solid {BORDER_SUBTLE}; border-radius: 10px; background: #FFFFFF; }}"
        )
        # The viewport is a separate child widget with its own opaque
        # square background - it isn't clipped to the frame's rounded
        # corners, so it was covering them with square white corners
        # right up against the curved border. Making it transparent lets
        # the frame's own rounded background paint through cleanly.
        scroll.viewport().setStyleSheet("background: transparent;")
        scroll.setWidgetResizable(True)
        grid_container = QWidget()
        self.grid = QGridLayout(grid_container)
        self.grid.setContentsMargins(12, 12, 12, 12)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll.setWidget(grid_container)
        outer.addWidget(scroll, 1)

        # Added to `root`, not `outer` - `outer` has a 16px margin on all
        # sides (for the cards above), which was insetting this bar's
        # border-top short of the actual window edges instead of letting
        # it span edge to edge like the title bar's own separator does.
        # Its own row supplies matching left/right padding instead, so
        # the text still lines up visually with the cards above it.
        txrx_bar = QWidget()
        txrx_bar.setAttribute(Qt.WA_StyledBackground, True)
        txrx_bar.setStyleSheet(f"border-top: 2px solid {BORDER_SUBTLE};")
        txrx_row = QHBoxLayout(txrx_bar)
        txrx_row.setContentsMargins(16, 8, 16, 8)
        txrx_row.setSpacing(16)

        # Left group: TX + RX, side by side.
        self.tx_value_label = QLabel("TX : --")
        self.rx_value_label = QLabel("RX : --")
        for lbl in (self.tx_value_label, self.rx_value_label):
            lbl.setStyleSheet(f"color: {ACCENT_BLUE}; font-weight: 600; font-size: 12px; border: none;")
        txrx_row.addWidget(self.tx_value_label)
        txrx_row.addWidget(self.rx_value_label)

        txrx_row.addStretch()

        # Right group: the "no response"/rejection warning, then Clear
        # Log - a command that never got acknowledged (module unplugged
        # mid-session, real hardware fault, etc.) has to surface
        # somewhere. Hidden until the first one, then auto-hides itself
        # after WARNING_DISPLAY_MS.
        self.warning_label = QLabel("")
        self.warning_label.setStyleSheet(
            f"color: {WARNING_TEXT}; background: {WARNING_BG}; border: 1px solid {WARNING_BORDER}; "
            f"border-radius: 6px; padding: 4px 10px; font-size: 12px;"
        )
        self.warning_label.setVisible(False)
        txrx_row.addWidget(self.warning_label)

        # Background/text match the app icon's own colors exactly (NAVY
        # #1F2937 background, ACCENT_BLUE #64AAFF text/glyph - checked
        # against the actual icon pixels).
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.setToolTip("Erase the app's log file (logs/sdr_controller.log)")
        self.clear_log_btn.setCursor(Qt.PointingHandCursor)
        self.clear_log_btn.setStyleSheet(
            f"QPushButton {{ background: {NAVY}; border: 1px solid {NAVY}; "
            f"border-radius: 5px; font-size: 11px; padding: 4px 10px; color: {ACCENT_BLUE}; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE}; color: {NAVY}; }}"
        )
        self.clear_log_btn.clicked.connect(self._on_clear_log)
        txrx_row.addWidget(self.clear_log_btn)

        root.addWidget(txrx_bar)

        self.setCentralWidget(central)

        self._cards = {}
        self.app.channels.channel_added.connect(self._on_channel_added)
        self.app.channels.channel_online.connect(self._on_channel_online)
        self.app.channels.channel_offline.connect(self._on_channel_offline)
        self.app.channels.discovery_progress.connect(self._on_discovery_progress)
        self.app.channels.discovery_finished.connect(self._on_discovery_finished)
        self.app.channels.command_timeout.connect(self._on_command_timeout)
        self.app.channels.raw_tx.connect(self._on_raw_tx)
        self.app.channels.raw_rx.connect(self._on_raw_rx)

        # Deliberately does NOT auto-scan on launch - scanning sends a
        # broadcast Address Query to every available port, and if two
        # modules are still sharing one converter (a real risk on the
        # current test rig), that's a bus collision every time it fires.
        # Scanning only happens when the user explicitly clicks Scan.

    def _on_discovery_progress(self, current: int, total: int):
        self.status_label.setText(f"Scanning… checked port {current}/{total}")

    def _on_discovery_finished(self):
        count = len(self._cards)
        self.status_label.setText(
            f"{count} channel(s) found." if count else
            "No devices found. Check wiring and power."
        )

    def _on_rescan(self):
        self.status_label.setText("Scanning… checking for channels")
        self.app.channels.start_discovery()

    def _on_clear_log(self):
        clear_log(self.app.logger)
        self.warning_label.setVisible(False)
        self.status_label.setText("Log cleared.")

    def _on_manual_ask(self):
        ports = ConnectionController.list_ports()
        ManualAddDialog.open(self, self.app.channels, ports)

    def _on_command_timeout(self, message: str):
        self.warning_label.setText(message)
        self.warning_label.setVisible(True)
        self._warning_timer.start(WARNING_DISPLAY_MS)

    def _on_raw_tx(self, address: int, data: bytes):
        self.tx_value_label.setText(f"TX : CH{address:02d} {data.hex(' ').upper()}")

    def _on_raw_rx(self, address: int, data: bytes):
        self.rx_value_label.setText(f"RX : CH{address:02d} {data.hex(' ').upper()}")

    def _on_channel_added(self, address: int):
        controller = self.app.channels.get_controller(address)
        state = self.app.channels.get_state(address)
        card = ChannelCard(controller, state)
        card.disconnect_requested.connect(self._on_disconnect_requested)
        self._cards[address] = card
        index = len(self._cards) - 1
        self.grid.addWidget(card, index // MAX_COLUMNS, index % MAX_COLUMNS)

    def _on_disconnect_requested(self, address: int):
        confirmed = ConfirmDialog.ask(
            self,
            "Disconnect Channel",
            f"Disconnect CH{address:02d}? Its output will be turned off "
            f"first, so it's safe to physically swap which module is wired in.",
            confirm_text="Disconnect",
            cancel_text="Cancel",
            danger=True,
        )
        if not confirmed:
            return
        # Immediate feedback that the click registered - turning the
        # output off and waiting for that to confirm before actually
        # disconnecting can take up to ~1s on unresponsive hardware, and
        # without this it looks like nothing happened during that wait.
        self.status_label.setText(f"Disconnecting CH{address:02d}…")
        self.app.channels.disconnect_channel_safely(address)

    def _on_channel_online(self, address: int):
        card = self._cards.get(address)
        if card is not None:
            card.set_online(self.app.channels.get_controller(address))

    def _on_channel_offline(self, address: int):
        card = self._cards.get(address)
        if card is not None:
            card.set_offline()
        self.status_label.setText(f"CH{address:02d} disconnected.")

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
            danger=True,
        )
        if not confirmed:
            return
        self.close()
