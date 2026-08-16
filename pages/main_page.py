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
from services.encoding import generate_key, encode_message
from services.protocol.packet_parser import describe_command
from styles.theme_colors import BORDER_SUBTLE, ACCENT_BLUE
from utils.logging_service import clear_log

TOP_ROW_HEIGHT = 90  # shared by Controls/Logs/Dev Logs, sitting side by side in the same row - one constant so they can't drift apart again
# Minimum widths, not fixed ones - all three cards share the row's
# width via QSizePolicy.Expanding + stretch factors below, shrinking
# together as the window narrows so all three stay on one row instead
# of any of them wrapping or getting clipped. These floors are just
# where each one stops being legible (Controls' button row, a couple
# of visible log lines).
CONTROLS_MIN_WIDTH = 260
LOGS_MIN_WIDTH = 260
DEV_LOGS_MIN_WIDTH = 200  # narrower floor than Logs - hex/encrypted-preview lines don't need to fit a whole sentence, just be readable

# Typed anywhere in the app (not a shortcut held down, a sequence typed
# one key after another) to toggle dev mode - deliberately not bound to
# any visible button or menu entry, see MainWindow.eventFilter. Matched
# against each keypress's actual produced character (event.text()), not
# the raw Qt.Key code - that's what makes "~" reliable across keyboard
# layouts, since which physical key/modifier combination produces a
# tilde varies by layout, but the character it produces doesn't. Leads
# with a symbol specifically so an ordinary word (someone typing "dev"
# in a normal sentence somewhere) can never accidentally match it.
DEV_MODE_SEQUENCE = ["`", "d", "e", "v"]
CHANNELS_PER_ROW = 4  # fixed - cards themselves stretch to fill the row instead of the column count changing


class MainWindow(QMainWindow):
    """One screen: a Controls status bar up top, then a grid of
    per-channel cards, every one already live and blind-sendable from
    launch - no Scan/+Addr discovery step. No Dashboard/Device Control/
    Communication pages, no sidebar, no Module Address field anywhere.

    This class is wiring, not implementation: Controls/Logs/Dev Logs
    are self-contained components (see components/controls_bar.py,
    components/logs_panel.py) that get instantiated and connected here,
    same as ChannelCard already was - MainWindow doesn't build their
    internals itself."""

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
        self._armed_card = None  # only one card unlocked at a time - see _on_card_armed
        self.app.channels.raw_tx.connect(self._on_raw_tx)
        self.app.channels.raw_rx.connect(self._on_raw_rx)

        # All 16 slots are visible and live from launch - every card
        # already has a real ChannelController (see ChannelManager) that
        # brute-force finds its own port and blind-sends every command,
        # no prior Scan/+Addr discovery step required.
        for address in range(MAX_CHANNELS):
            self._build_card(address)

        self.dev_mode = False
        self._dev_key_buffer = []
        # Demo-only, per-session key for the encode_message() preview
        # dev mode shows on TX lines - not tied to any real service or
        # persisted anywhere, since real key distribution between this
        # app and an external party is a separate problem for whenever
        # that service actually gets built (see services/encoding.py).
        self._dev_encryption_key = generate_key()

        # App-wide filter (not just a handler on this window) so a click
        # ANYWHERE that isn't on the currently-armed card - empty space,
        # another button, a dialog - locks it back down too, not just a
        # click on a different card. A card left armed with nothing else
        # going on is still a card whose controls could send by accident.
        # Also where the dev-mode key sequence is caught, for the same
        # reason - it has to see every keypress app-wide, not just ones
        # landing on a specific focused widget.
        QApplication.instance().installEventFilter(self)

    def _apply_window_chrome(self):
        self.resize(1040, 780)
        # The grid is always CHANNELS_PER_ROW (4) columns wide (see
        # _reflow_grid) - this floor keeps each of those 4 columns at
        # least ChannelCard.MIN_WIDTH wide even at minimum size, so cards
        # never get squeezed narrower than that instead of adding more
        # columns the way the old width-based reflow used to. Cards fill
        # 100% of the window's width regardless (Expanding + column
        # stretch), so a narrower default window is what actually makes
        # them render narrower - MIN_WIDTH alone is just the floor.
        self.setMinimumSize(1000, 700)
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

    def _build_top_row(self) -> QHBoxLayout:
        """Controls, Logs, and Dev Logs: three self-contained components,
        instantiated and wired here, sharing one row height
        (TOP_ROW_HEIGHT) so they can't drift apart. This is the whole
        point of pulling them out into components/ - this method reads
        as what's on screen and what it's connected to, not how a
        QListWidget gets styled."""
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        self.controls_bar = ControlsBar(min_width=CONTROLS_MIN_WIDTH)
        self.controls_bar.setFixedHeight(TOP_ROW_HEIGHT)
        self.controls_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.controls_bar.query_requested.connect(self._on_query)
        self.controls_bar.clear_log_requested.connect(self._on_clear_log)
        top_row.addWidget(self.controls_bar, 3, alignment=Qt.AlignTop)

        # Live TX/RX byte log, right beside Controls - every real write
        # and every real read, across every card AND Query, land here
        # (see ChannelManager.raw_tx/raw_rx, wired to _on_raw_tx/
        # _on_raw_rx below).
        self.logs_panel = LogsPanel("Logs", icon="fa5s.list", min_width=LOGS_MIN_WIDTH)
        self.logs_panel.setFixedHeight(TOP_ROW_HEIGHT)
        self.logs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        top_row.addWidget(self.logs_panel, 4, alignment=Qt.AlignTop)

        # Hidden unless dev mode is on (see _track_dev_mode_key) - the
        # hex/encrypted-preview detail used to get appended onto the
        # main Logs panel's lines, which just made them run long enough
        # to truncate in a card this width. A separate panel means the
        # main log stays exactly as clean as it is for everyone else.
        self.dev_logs_panel = LogsPanel("Dev Logs", icon="fa5s.code", min_width=DEV_LOGS_MIN_WIDTH)
        self.dev_logs_panel.setFixedHeight(TOP_ROW_HEIGHT)
        self.dev_logs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.dev_logs_panel.setVisible(False)
        top_row.addWidget(self.dev_logs_panel, 3, alignment=Qt.AlignTop)

        return top_row

    def _build_channels_scroll(self) -> QScrollArea:
        # No border/fill of its own - purely a scroll mechanism around the
        # grid, not a bordered section like Controls/Logs. Each card
        # already carries its own border (see ChannelCard.arm/disarm), so
        # a second border wrapping all of them just added a redundant
        # outline with nothing meaningful of its own to signal. Scoped to
        # #ChannelsScroll so it doesn't cascade onto the cards inside it.
        scroll = QScrollArea()
        scroll.setObjectName("ChannelsScroll")
        # The scrollbar itself was still the plain native OS one (grey
        # track, square arrow buttons) - the one leftover bit of chrome
        # that didn't match anything else in the app. A slim, arrow-less,
        # rounded thumb reads as part of this app instead.
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
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll.setWidget(grid_container)
        return scroll

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

        if event.type() == QEvent.KeyPress and obj is self:
            # An unhandled key press bubbles up through every ancestor
            # widget (confirmed via logging: QWindow -> ... -> Card ->
            # ResizableContainer -> MainWindow), and since this is an
            # app-wide filter, eventFilter gets called once per hop for
            # what is conceptually one physical keystroke. MainWindow
            # (self) is always the final, single stop in that chain, so
            # gating on obj is self counts each keystroke exactly once
            # instead of once per ancestor. Event-object identity doesn't
            # work for this dedup - QEvent isn't a QObject, so PySide
            # doesn't guarantee the same Python wrapper across hops.
            self._track_dev_mode_key(event)

        return super().eventFilter(obj, event)

    def _track_dev_mode_key(self, event):
        # Ignore OS key-repeat - holding a key down for even a fraction
        # of a second past the repeat threshold floods the buffer with
        # copies of that one character, pushing the earlier distinct
        # keys of the sequence out of the last-4 window before the
        # diverse sequence ever lines up. Only a key's initial press
        # counts.
        if event.isAutoRepeat():
            return

        # Backtick is matched by its raw key code, not event.text() - on
        # layouts where it's a dead key (e.g. Windows "US-International"),
        # pressing it alone doesn't produce a character until combined
        # with the next keystroke, so text() would come back empty/late
        # and silently drop it here. The key code fires immediately
        # regardless of that composition state.
        if event.key() == Qt.Key_QuoteLeft:
            char = "`"
        elif event.text():
            char = event.text().lower()
        else:
            return

        # A rolling buffer, not a "must start fresh" match - mistyping
        # the sequence shouldn't require deliberately doing something
        # else first before trying again, it should just fall out the
        # end as the buffer keeps sliding.
        self._dev_key_buffer.append(char)
        self._dev_key_buffer = self._dev_key_buffer[-len(DEV_MODE_SEQUENCE):]
        if self._dev_key_buffer == DEV_MODE_SEQUENCE:
            self._dev_key_buffer = []
            self.dev_mode = not self.dev_mode
            self.title_bar.set_dev_mode(self.dev_mode)
            self.dev_logs_panel.setVisible(self.dev_mode)

    # Click -> _on_query() -> self.app.channels.brute_force_query()
    # (hooks/use_channels.py). The ONE control in this app that is NOT
    # a blind send: it waits for and verifies a real response instead
    # of firing the command and moving on, unlike every channel card's
    # toggle/slider (see components/channel_card.py). Wired from
    # ControlsBar.query_requested in _build_top_row above.
    def _on_query(self):
        address, ok = QInputDialog.getInt(self, "Query", "Address to send to:", 1, 0, 199)
        if not ok:
            return
        choice, ok = QInputDialog.getItem(self, "Query", "Output:", ["ON", "OFF"], editable=False)
        if not ok:
            return
        self.controls_bar.set_status(f"Querying {choice} to address {address}…")
        self.app.channels.brute_force_query(address, on=(choice == "ON"))

    # Wired from ControlsBar.clear_log_requested in _build_top_row above.
    def _on_clear_log(self):
        clear_log(self.app.logger)
        self.logs_panel.clear()
        self.dev_logs_panel.clear()
        self.controls_bar.set_status("Log cleared.")

    def _on_raw_tx(self, address: int, data: bytes):
        # address is already the wire address (1-16, matches the CH
        # number on screen) - see ChannelManager.raw_tx. Always decoded
        # only here - this panel is meant to read at a glance, not for
        # byte-level debugging, regardless of dev mode. The raw wire
        # bytes and a live encode_message() preview go to the separate
        # Dev Logs panel instead (see _track_dev_mode_key) - the actual
        # human action -> hardware bytes -> what an encrypted API
        # message for it would look like, visible on demand without
        # ever making this panel's own lines run long. That encrypted
        # preview is a demo of the mechanism, not a real message going
        # anywhere yet - see services/encoding.py.
        decoded = describe_command(data)
        self.logs_panel.append_line(f"TX CH{address:02d}: {decoded}")
        if self.dev_mode:
            payload = {"channel": address, "command": decoded}
            encoded_value = encode_message(payload, self._dev_encryption_key)
            # Two separate list items, not one line with an embedded
            # newline - QListWidget doesn't grow a row's height for
            # multi-line text without extra delegate/word-wrap setup,
            # so an embedded \n would just get squashed into one row.
            self.dev_logs_panel.append_line(f"CH{address:02d}: {data.hex(' ').upper()}")
            self.dev_logs_panel.append_line(f"ENC: {encoded_value}")

    def _on_raw_rx(self, address: int, data: bytes):
        self.logs_panel.append_line(f"RX CH{address:02d}: {data.hex(' ').upper()}")

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
        # width-based reflow that had to be recomputed on every resize -
        # no resizeEvent/showEvent hook needed for this anymore.
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
