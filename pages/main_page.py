from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QScrollArea, QPushButton
)
from PySide6.QtCore import Qt, QTimer

from components import (
    ChannelCard, ConfirmDialog,
    TitleBar, ResizableContainer, make_card,
)
from hooks.use_channels import MAX_CHANNELS
from styles.theme_colors import (
    TEXT_MUTED, TEXT_DARK, BORDER_SUBTLE, WARNING_TEXT, WARNING_BG, WARNING_BORDER,
    ACCENT_BLUE, NAVY,
)
from utils.logging_service import clear_log

WARNING_DISPLAY_MS = 6000


TOP_CARD_SIZE = (320, 120)


class MainWindow(QMainWindow):
    """One screen: a Controls status bar up top, then a grid of
    per-channel cards, every one already live and blind-sendable from
    launch - no Scan/+Addr discovery step. No Dashboard/Device Control/
    Communication pages, no sidebar, no Module Address field anywhere."""

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

        controls_card = make_card("Controls", icon="fa5s.sliders-h")
        controls_card.setFixedSize(*TOP_CARD_SIZE)

        status_row = QHBoxLayout()
        # Every channel is live and blind-sendable the moment the app
        # launches - no Scan/+Addr step to wait on (see ChannelManager).
        # This label is just a running status line for the last action
        # taken (a blind-send in flight, a disconnect, etc).
        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        controls_card.body_layout.addLayout(status_row)

        top_row.addWidget(controls_card, alignment=Qt.AlignTop)

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
        self.channels_scroll = scroll
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
        self.app.channels.command_timeout.connect(self._on_command_timeout)
        self.app.channels.raw_tx.connect(self._on_raw_tx)
        self.app.channels.raw_rx.connect(self._on_raw_rx)

        # All 16 slots are visible and live from launch - every card
        # already has a real ChannelController (see ChannelManager) that
        # brute-force finds its own port and blind-sends every command,
        # no prior Scan/+Addr discovery step required.
        for address in range(MAX_CHANNELS):
            self._build_card(address)

    def _on_clear_log(self):
        clear_log(self.app.logger)
        self.warning_label.setVisible(False)
        self.status_label.setText("Log cleared.")

    def _on_command_timeout(self, message: str):
        self.warning_label.setText(message)
        self.warning_label.setVisible(True)
        self._warning_timer.start(WARNING_DISPLAY_MS)

    def _on_raw_tx(self, address: int, data: bytes):
        self.tx_value_label.setText(f"TX : CH{address:02d} {data.hex(' ').upper()}")

    def _on_raw_rx(self, address: int, data: bytes):
        self.rx_value_label.setText(f"RX : CH{address:02d} {data.hex(' ').upper()}")

    def _build_card(self, address: int):
        controller = self.app.channels.get_controller(address)
        state = self.app.channels.get_state(address)
        card = ChannelCard(controller, state)
        self._cards[address] = card
        self._reflow_grid()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_grid()

    def _reflow_grid(self):
        # Cards are a fixed width (ChannelCard.WIDTH), so the grid was
        # stuck at a hardcoded column count regardless of how wide the
        # window actually was - full screen just left empty space on the
        # right instead of using it. Recomputing how many columns fit the
        # Channels box's actual current width, and re-placing every card
        # accordingly, makes it respond to the real window size instead.
        if not self._cards:
            return
        available = self.channels_scroll.viewport().width()
        margins = self.grid.contentsMargins()
        available -= margins.left() + margins.right()
        spacing = self.grid.spacing()
        columns = max(1, (available + spacing) // (ChannelCard.WIDTH + spacing))
        for index, address in enumerate(sorted(self._cards)):
            row, col = divmod(index, columns)
            self.grid.addWidget(self._cards[address], row, col)

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
