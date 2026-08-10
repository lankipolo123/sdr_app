import qtawesome as qta

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QScrollArea, QPushButton, QInputDialog, QApplication, QListWidget
)
from PySide6.QtCore import Qt, QEvent

from components import (
    ChannelCard, ConfirmDialog, LogsDialog,
    TitleBar, ResizableContainer, make_card,
)
from hooks.use_channels import MAX_CHANNELS
from styles.theme_colors import TEXT_MUTED, TEXT_DARK, BORDER_SUBTLE, ACCENT_BLUE, NAVY
from utils.logging_service import clear_log

TOP_CARD_SIZE = (320, 120)
LOG_CARD_HEIGHT = 120  # matches TOP_CARD_SIZE's height, sits at the same row
LOG_MAX_ENTRIES = 200  # oldest entries drop off - a running session shouldn't grow this unbounded
CHANNELS_PER_ROW = 4  # fixed - cards themselves stretch to fill the row instead of the column count changing


class MainWindow(QMainWindow):
    """One screen: a Controls status bar up top, then a grid of
    per-channel cards, every one already live and blind-sendable from
    launch - no Scan/+Addr discovery step. No Dashboard/Device Control/
    Communication pages, no sidebar, no Module Address field anywhere."""

    def __init__(self, app_controller):
        super().__init__()
        self.app = app_controller
        self.setWindowTitle("SDR App")
        self.resize(1200, 780)
        # The grid is always CHANNELS_PER_ROW (4) columns wide (see
        # _reflow_grid) - this floor keeps each of those 4 columns at
        # least ChannelCard.MIN_WIDTH wide even at minimum size, so cards
        # never get squeezed narrower than that instead of adding more
        # columns the way the old width-based reflow used to.
        self.setMinimumSize(1150, 700)
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
        self.query_btn = QPushButton("Query")
        self.query_btn.setToolTip(
            "Diagnostic: ask one specific address directly, brute-force "
            "finding the port, and actually wait for and verify a real "
            "confirmed response (or report failure) - separate from the "
            "cards, which still send blind"
        )
        self.query_btn.setStyleSheet(f"QPushButton {{ border: 1px solid {BORDER_SUBTLE}; border-radius: 5px; }}")
        self.query_btn.clicked.connect(self._on_query)
        status_row.addWidget(self.query_btn)

        # Background/text match the app icon's own colors exactly (NAVY
        # #1F2937 background, ACCENT_BLUE #64AAFF text/glyph - checked
        # against the actual icon pixels).
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.setToolTip(
            "Erase the app's log file (logs/sdr_controller.log) and the "
            "TX/RX list above"
        )
        self.clear_log_btn.setCursor(Qt.PointingHandCursor)
        self.clear_log_btn.setStyleSheet(
            f"QPushButton {{ background: {NAVY}; border: 1px solid {NAVY}; "
            f"border-radius: 5px; font-size: 11px; padding: 4px 10px; color: {ACCENT_BLUE}; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE}; color: {NAVY}; }}"
        )
        self.clear_log_btn.clicked.connect(self._on_clear_log)
        status_row.addWidget(self.clear_log_btn)
        controls_card.body_layout.addLayout(status_row)

        top_row.addWidget(controls_card, alignment=Qt.AlignTop)

        # Live TX/RX byte log, right beside Controls - every real write
        # and every real read, across every card AND Query, land here
        # (see ChannelManager.raw_tx/raw_rx). Replaces the single
        # last-value labels that used to sit in the bottom bar - those
        # were wired to signals that ChannelManager never actually
        # emitted, so they never updated at all.
        logs_card = make_card("Logs", icon="fa5s.list")
        logs_card.setFixedHeight(LOG_CARD_HEIGHT)
        # Opens the same log in a bigger, resizable, scrollable dialog
        # (see LogsDialog) - the card itself only ever has room for a
        # handful of visible lines.
        self.maximize_logs_btn = QPushButton()
        self.maximize_logs_btn.setIcon(qta.icon("fa5s.expand-alt", color=ACCENT_BLUE))
        self.maximize_logs_btn.setFixedSize(20, 20)
        self.maximize_logs_btn.setCursor(Qt.PointingHandCursor)
        self.maximize_logs_btn.setToolTip("Open full scrollable log")
        self.maximize_logs_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; }"
            f"QPushButton:hover {{ background: {BORDER_SUBTLE}; border-radius: 4px; }}"
        )
        self.maximize_logs_btn.clicked.connect(self._on_open_logs_dialog)
        logs_card.header_layout.addWidget(self.maximize_logs_btn)
        self.log_list = QListWidget()
        self.log_list.setStyleSheet(
            f"QListWidget {{ border: none; font-size: 11px; color: {TEXT_DARK}; }}"
        )
        logs_card.body_layout.addWidget(self.log_list)
        top_row.addWidget(logs_card, 1, alignment=Qt.AlignTop)
        self.logs_dialog = None  # only built the first time it's opened - see _on_open_logs_dialog

        outer.addLayout(top_row)

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

        self.setCentralWidget(central)

        self._cards = {}
        self._armed_card = None  # only one card unlocked at a time - see _on_card_armed
        self.app.channels.raw_tx.connect(self._on_raw_tx)
        self.app.channels.raw_rx.connect(self._on_raw_rx)

        # All 16 slots are visible and live from launch - every card
        # already has a real ChannelController (see ChannelManager) that
        # brute-force finds its own port and blind-sends every command,
        # no prior Scan/+Addr discovery step required.
        for address in range(MAX_CHANNELS):
            self._build_card(address)

        # App-wide filter (not just a handler on this window) so a click
        # ANYWHERE that isn't on the currently-armed card - empty space,
        # another button, a dialog - locks it back down too, not just a
        # click on a different card. A card left armed with nothing else
        # going on is still a card whose controls could send by accident.
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        # The app-wide filter sees every QObject's events, not just
        # QWidgets - a real windowing system also routes clicks through
        # QWindow (native window decorations, etc.), and isAncestorOf()
        # only accepts a QWidget. Anything that isn't one can't be a
        # click on a card in the first place, so there's nothing to
        # check - but it also isn't a reason to disarm (a native window
        # event isn't the user clicking away from the card).
        #
        # A combo box's dropdown list is its own top-level popup, not a
        # child of the card in Qt's widget tree - isAncestorOf() would
        # say a click on an item in that list is "outside" the card and
        # disarm it mid-selection, disabling the combo box right as Qt
        # is processing the click that was supposed to pick a mode.
        # QApplication.activePopupWidget() is non-None for exactly this
        # kind of transient popup (combo dropdowns, context menus) -
        # skip the disarm check entirely while one's open.
        if (
            event.type() == QEvent.MouseButtonPress
            and self._armed_card is not None
            and isinstance(obj, QWidget)
            and QApplication.activePopupWidget() is None
        ):
            if not (obj is self._armed_card or self._armed_card.isAncestorOf(obj)):
                self._armed_card.disarm()
                self._armed_card = None
        return super().eventFilter(obj, event)

    def _on_query(self):
        address, ok = QInputDialog.getInt(self, "Query", "Address to send to:", 1, 0, 199)
        if not ok:
            return
        choice, ok = QInputDialog.getItem(self, "Query", "Output:", ["ON", "OFF"], editable=False)
        if not ok:
            return
        self.status_label.setText(f"Querying {choice} to address {address}…")
        self.app.channels.brute_force_query(address, on=(choice == "ON"))

    def _on_clear_log(self):
        clear_log(self.app.logger)
        self.log_list.clear()
        if self.logs_dialog is not None:
            self.logs_dialog.list.clear()
        self.status_label.setText("Log cleared.")

    def _on_open_logs_dialog(self):
        if self.logs_dialog is None:
            lines = [self.log_list.item(i).text() for i in range(self.log_list.count())]
            self.logs_dialog = LogsDialog(self, lines)
        self.logs_dialog.show()
        self.logs_dialog.raise_()
        self.logs_dialog.activateWindow()

    def _on_raw_tx(self, address: int, data: bytes):
        # address is already the wire address (1-16, matches the CH
        # number on screen) - see ChannelManager.raw_tx.
        self._append_log(f"TX CH{address:02d}: {data.hex(' ').upper()}")

    def _on_raw_rx(self, address: int, data: bytes):
        self._append_log(f"RX CH{address:02d}: {data.hex(' ').upper()}")

    def _append_log(self, line: str):
        self.log_list.addItem(line)
        while self.log_list.count() > LOG_MAX_ENTRIES:
            self.log_list.takeItem(0)
        self.log_list.scrollToBottom()
        # Keep the maximized view (if it's open) live too, instead of
        # only reflecting whatever existed at the moment it was opened.
        if self.logs_dialog is not None and self.logs_dialog.isVisible():
            self.logs_dialog.append_line(line, LOG_MAX_ENTRIES)

    def _build_card(self, address: int):
        controller = self.app.channels.get_controller(address)
        state = self.app.channels.get_state(address)
        card = ChannelCard(controller, state)
        card.armed.connect(lambda c=card: self._on_card_armed(c))
        self._cards[address] = card
        self._reflow_grid()

    def _on_card_armed(self, card: ChannelCard):
        # Only one card is ever armed at once - tapping a new one locks
        # whichever was previously armed back down, so its controls
        # can't still send by accident once attention has moved on.
        if self._armed_card is not None and self._armed_card is not card:
            self._armed_card.disarm()
        self._armed_card = card

    def _reflow_grid(self):
        # Always 4 columns, regardless of window width - cards themselves
        # stretch to fill their share (see ChannelCard's Expanding size
        # policy + the column stretch factors below), so "responsive"
        # means the CARDS grow/shrink with the window, not the column
        # count. This only ever needs to run once per card as it's built
        # (column positions never change afterward), unlike the old
        # width-based column count that had to be recomputed on every
        # resize - no resizeEvent/showEvent hook needed for this anymore.
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
