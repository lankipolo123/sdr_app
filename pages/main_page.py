import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QSizePolicy, QPushButton, QFileDialog, QFrame, QLabel
)
from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtGui import QIcon, QPixmap, QPainter

from components import (
    ChannelCard, ConfirmDialog, CloseConfirmDialog, ResetProgressOverlay, LogsPanel,
    TitleBar, ResizableContainer, SensorCard, SensorHeatmap,
    BulkActionsBar, KillSwitchBanner, SpectrumPanel, SummaryPanel,
)
from hooks.use_channels import MAX_CHANNELS
from services.middleware import dll_decode_frame
from styles import theme_colors
from utils.time_format import format_uptime
from utils.app_paths import branding_icon_path, resolve_app_icon_path

# Layout mirrors sdr_c's actual window (Connection/Sensors + heatmap +
# Bulk Actions in one header band; a narrow sidebar - Activity Log there
# - beside the channel grid; Commands as its own full-width panel below
# the grid, not above it). Same panels sdr_app already had, just placed
# the way the C rewrite places them instead of everything stacked
# full-width in one column.
HEADER_ROW_HEIGHT = 150
SENSOR_MIN_WIDTH = 260
BULK_ACTIONS_MIN_WIDTH = 320
SIDEBAR_WIDTH = 480
SIDEBAR_MAX_WIDTH = 680
# Narrower than a panel stretched to fill whatever header space is
# left over - but same HEADER_ROW_HEIGHT as its header-row neighbors
# (sensor card, bulk actions), not shorter: shrinking the height too
# also shrank the faded emblem watermark drawn inside it (sized off
# the panel's smaller dimension) and made it look like an odd little
# card rather than lining up with the row around it.
HEATMAP_WIDTH = 340
HEATMAP_MAX_WIDTH = 560
HEATMAP_HEIGHT = HEADER_ROW_HEIGHT

CHANNELS_PER_ROW = 4
BRANDING_ICON_SIZE = 256
BRAND_ICON_SIZE = 108


class _BrandMarkIcon(QWidget):
    """Helix Defense header mark. Shows the SAME resolved icon as the
    window/taskbar/title bar (utils/app_paths.resolve_app_icon_path()) -
    a Change Logo/Reset updates this too, not just the OS-level icon.
    Not the heatmap's separate emblem watermark, which stays its own
    fixed diamond+triangle design."""

    def __init__(self):
        super().__init__()
        self._pixmap = QPixmap()

    def refresh(self, icon_path: str | None):
        self._pixmap = QPixmap(icon_path) if icon_path else QPixmap()
        self.update()

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


class MainWindow(QMainWindow):

    def __init__(self, app_controller):
        super().__init__()
        self.app = app_controller
        self.setWindowTitle("Pseudo Random Noise Controller")
        self._apply_window_chrome()
        self._cards = {}

        # Connected once here, not inside _build_ui(): these target
        # MainWindow's own methods, which stay alive across a theme
        # toggle's rebuild - reconnecting them there would stack a
        # duplicate connection on every toggle. Each handler looks up
        # its target child widget (self.logs_panel, self.sensor_card, …)
        # fresh at call time, so it keeps working once _build_ui()
        # repoints those attributes at freshly built widgets.
        self.app.uptime_changed.connect(self._on_uptime_changed)
        self.app.channels.raw_tx.connect(self._on_raw_tx)
        self.app.channels.raw_rx.connect(self._on_raw_rx)
        self.app.sensor.changed.connect(self._on_sensor_changed)

        self._build_ui()

    def _build_ui(self):
        """Builds (or, on a theme toggle, rebuilds) everything below the
        window chrome. Direct port of the rebuild sdr_c itself does in
        on_theme_toggle_clicked() (main.c) - it rebuilds every themed
        GDI object and repaints, rather than patching colors in place.
        Safe to call again later: the old central widget (and every
        child widget under it - cards, panels, the old title bar) is
        torn down and a fresh one takes its place."""
        central = ResizableContainer(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(self, "Pseudo Random Noise Controller", icon=self.windowIcon())
        self.title_bar.close_app_requested.connect(self._on_close_app_clicked)
        self._build_title_bar_actions()
        root.addWidget(self.title_bar)

        self.kill_switch_banner = KillSwitchBanner(self.app)
        root.addWidget(self.kill_switch_banner)

        self._on_uptime_changed(self.app.current_uptime_seconds())

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        root.addWidget(content, 1)

        outer.addLayout(self._build_header_row())
        outer.addLayout(self._build_body_row(), 1)

        self.summary_panel = SummaryPanel(self.app)
        self.summary_panel.theme_toggle_requested.connect(self._on_theme_toggle_requested)
        outer.addWidget(self.summary_panel)

        old_central = self.centralWidget()
        self.setCentralWidget(central)
        if old_central is not None:
            old_central.deleteLater()

        self._cards.clear()
        for address in range(MAX_CHANNELS):
            self._build_card(address)

        self._refresh_sensor_ports()
        self._on_sensor_changed()

    def _on_theme_toggle_requested(self):
        from PySide6.QtWidgets import QApplication
        theme_colors.set_light_mode(not theme_colors.is_light_mode())
        self.app.config.set("light_mode", theme_colors.is_light_mode())
        self.app.config.save()
        qt_app = QApplication.instance()
        qt_app.setPalette(theme_colors.app_palette())
        qt_app.setStyleSheet(theme_colors.build_global_qss())
        self._build_ui()

    def _apply_window_chrome(self):
        self.resize(1300, 960)
        # Wide enough that the sidebar's own minimum (SIDEBAR_WIDTH) and
        # the grid's own 4-column minimum can both actually fit at once -
        # the old 1100 predates the wider sidebar and let the window
        # shrink past what the layout truly needs, silently clipping the
        # 4th column instead of showing a scrollbar for it (a bare
        # QScrollArea's setWidgetResizable(True) ties its content's size
        # to the viewport it's GIVEN, so if the window itself shrinks
        # past the layout's real minimum, there's no leftover space left
        # for a scrollbar to reveal - the content just gets compressed
        # along with everything else).
        self.setMinimumSize(1340, 820)
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def _build_header_row(self) -> QHBoxLayout:
        # Brand mark pinned to the left corner; Connection/sensor status,
        # the heatmap, and Bulk Actions all grouped together on the
        # right instead of spread across the row - direct follow-up
        # request. Same panels sdr_c's own header has, just pushed to
        # one side so the left corner is free for branding.
        #
        # No addStretch() between the brand mark and this group - a
        # blank spacer there just eats whatever room the window has,
        # which at a wide window size reads as a big dead gap between
        # the logo and everything else (direct report: "unnecessary
        # space"). The heatmap itself takes the stretch instead
        # (Expanding width, capped at HEATMAP_MAX_WIDTH) so that same
        # leftover room actually grows a real panel - also the honest
        # fix for "make the heatmap wider", since it now really does
        # scale with the window instead of sitting at one fixed size.
        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        header_row.addWidget(self._build_brand_mark(), 0, alignment=Qt.AlignVCenter)

        self.sensor_card = SensorCard(min_width=SENSOR_MIN_WIDTH)
        self.sensor_card.setFixedHeight(HEADER_ROW_HEIGHT)
        self.sensor_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.sensor_card.connect_requested.connect(self._on_sensor_connect)
        self.sensor_card.disconnect_requested.connect(self.app.sensor.disconnect)
        self.sensor_card.refresh_requested.connect(self._refresh_sensor_ports)
        header_row.addWidget(self.sensor_card, 0, alignment=Qt.AlignTop)

        heatmap = SensorHeatmap(self.app.sensor)
        heatmap.setMinimumSize(HEATMAP_WIDTH, HEATMAP_HEIGHT)
        heatmap.setMaximumWidth(HEATMAP_MAX_WIDTH)
        heatmap.setMaximumHeight(HEATMAP_HEIGHT)
        heatmap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        header_row.addWidget(heatmap, 1, alignment=Qt.AlignTop)

        self.bulk_actions_bar = BulkActionsBar(self.app)
        self.bulk_actions_bar.setFixedHeight(HEADER_ROW_HEIGHT)
        self.bulk_actions_bar.setMinimumWidth(BULK_ACTIONS_MIN_WIDTH)
        self.bulk_actions_bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        header_row.addWidget(self.bulk_actions_bar, 0, alignment=Qt.AlignTop)

        return header_row

    def _build_brand_mark(self) -> QWidget:
        # Icon centered, wordmark centered underneath - sdr_c's own
        # layout (main.c draws the mark at a fixed point, then the
        # "HELIX DEFENSE" wordmark in a centered rect directly below
        # it), not the icon-beside-text lockup this had before.
        #
        # Icon is _BrandMarkIcon (4 ascending vertical bars by default) -
        # direct request ("the vertical bars... as an icon on helix
        # defender"), replacing the app_icon.png/diamond+triangle mark
        # tried before - and, like the window/taskbar/title bar icon,
        # swaps to a custom logo via Change Logo/Reset.
        mark = QWidget()
        layout = QVBoxLayout(mark)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignHCenter)

        self.brand_mark_icon = _BrandMarkIcon()
        self.brand_mark_icon.setFixedSize(BRAND_ICON_SIZE, BRAND_ICON_SIZE)
        self.brand_mark_icon.refresh(resolve_app_icon_path())
        layout.addWidget(self.brand_mark_icon, 0, alignment=Qt.AlignHCenter)

        text_label = QLabel("HELIX DEFENSE")
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setStyleSheet(
            f"color: {theme_colors.TEXT_DARK}; font-size: 18px; font-weight: 900; letter-spacing: 3px;"
        )
        layout.addWidget(text_label, 0, alignment=Qt.AlignHCenter)

        return mark

    def _build_body_row(self) -> QHBoxLayout:
        # Narrow sidebar (Spectrum on top, Activity Log below) beside
        # the channel grid, same split sdr_c's own sidebar makes against
        # its channel grid - not a full-width strip above everything.
        body_row = QHBoxLayout()
        body_row.setSpacing(16)

        sidebar = QVBoxLayout()
        sidebar.setSpacing(16)

        self.spectrum_panel = SpectrumPanel(self.app.channels)
        self.spectrum_panel.setMinimumWidth(SIDEBAR_WIDTH)
        self.spectrum_panel.setMaximumWidth(SIDEBAR_MAX_WIDTH)
        self.spectrum_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sidebar.addWidget(self.spectrum_panel, 3)

        self.logs_panel = LogsPanel("Logs", icon="list.png", min_width=SIDEBAR_WIDTH)
        self.logs_panel.setMinimumWidth(SIDEBAR_WIDTH)
        self.logs_panel.setMaximumWidth(SIDEBAR_MAX_WIDTH)
        self.logs_panel.setMinimumHeight(150)
        self.logs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sidebar.addWidget(self.logs_panel, 2)

        # Sidebar gets a bigger share of the growth than sdr_c's own
        # 25%/75% split - direct follow-up request, the cards looked
        # better with less of the extra width pushed into them.
        body_row.addLayout(sidebar, 2)
        body_row.addWidget(self._build_channels_scroll(), 3)

        return body_row

    def _build_title_bar_actions(self):
        change_logo_btn = QPushButton("Change Logo…")
        change_logo_btn.setCursor(Qt.PointingHandCursor)
        change_logo_btn.setToolTip("Pick a custom app icon - applies everywhere immediately, no restart")
        change_logo_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme_colors.ACCENT_BLUE}; border: 1px solid {theme_colors.ACCENT_BLUE}; "
            f"border-radius: 4px; font-size: 10px; padding: 3px 8px; }}"
            f"QPushButton:hover {{ background: {theme_colors.ACCENT_BLUE}; color: {theme_colors.NAVY}; }}"
        )
        change_logo_btn.clicked.connect(self._on_change_logo_clicked)
        self.title_bar.add_action_widget(change_logo_btn)

        reset_logo_btn = QPushButton("Reset")
        reset_logo_btn.setCursor(Qt.PointingHandCursor)
        reset_logo_btn.setToolTip("Restore the default icon")
        reset_logo_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme_colors.ACCENT_BLUE}; border: 1px solid {theme_colors.ACCENT_BLUE}; "
            f"border-radius: 4px; font-size: 10px; padding: 3px 8px; }}"
            f"QPushButton:hover {{ background: {theme_colors.ACCENT_BLUE}; color: {theme_colors.NAVY}; }}"
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
            f"QPushButton {{ background: {theme_colors.STATUS_ERROR}; color: white; border: 1px solid {theme_colors.STATUS_ERROR}; "
            f"border-radius: 4px; font-size: 10px; font-weight: 600; padding: 3px 8px; }}"
            f"QPushButton:hover {{ background: {theme_colors.STATUS_ERROR_DARK}; }}"
        )
        force_trip_btn.clicked.connect(self._on_force_trip_clicked)
        self.title_bar.add_action_widget(force_trip_btn)

    def _build_channels_scroll(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("ChannelsScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"#ChannelsScroll {{ border: none; background: {theme_colors.PAGE_BG}; }}")
        scroll.viewport().setStyleSheet("background: transparent;")
        scroll.setWidgetResizable(True)
        # A bare QScrollArea's own minimumSizeHint has no idea its
        # scrollable content actually needs 4 columns' worth of width -
        # left unset, body_row's stretch (sidebar:grid) just splits
        # whatever space exists proportionally with no regard for what
        # the grid structurally needs, which silently starved it a few
        # px short of 4 full columns and forced an unwanted horizontal
        # scrollbar even at the window's normal default size. Setting
        # this floor makes that need visible to the layout, so stretch
        # only ever divides genuine leftover space beyond it.
        scroll.setMinimumWidth(
            CHANNELS_PER_ROW * ChannelCard.MIN_WIDTH + (CHANNELS_PER_ROW - 1) * 8 + 16 + 20
        )
        # Left "as needed", not off - 4 columns at their own MIN_WIDTH
        # plus the sidebar's own minimum can still outgrow a small
        # custom window size (turning it off entirely used to just
        # silently clip the 4th column instead of scrolling to it,
        # a real regression the widened sidebar surfaced).
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        _HSCROLLBAR_QSS = f"""
            QScrollBar:horizontal {{
                background: transparent;
                height: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {theme_colors.BORDER_SUBTLE};
                border-radius: 5px;
                min-width: 24px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {theme_colors.ACCENT_BLUE};
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{
                width: 0px;
                background: transparent;
                border: none;
            }}
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
        """
        scroll.horizontalScrollBar().setStyleSheet(_HSCROLLBAR_QSS)
        # Styled directly on the scrollbar widget itself, not via a
        # `#ChannelsScroll QScrollBar:vertical` descendant selector on
        # the scroll area - that selector didn't reliably win against
        # the app-wide stylesheet on every platform, leaving a plain
        # unstyled native-looking bar rather than this thin rounded one
        # (direct report, with a screenshot showing exactly that).
        scroll.verticalScrollBar().setStyleSheet(f"""
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {theme_colors.BORDER_SUBTLE};
                border-radius: 5px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {theme_colors.ACCENT_BLUE};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
                background: transparent;
                border: none;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)
        self.channels_scroll = scroll
        grid_container = QWidget()
        # setWidgetResizable(True) ties this widget's size to the
        # viewport's, which can shrink it - and everything inside -
        # below its own layout's true minimum instead of leaving the
        # excess to a horizontal scrollbar, unless the widget itself
        # also states that floor explicitly (matches scroll's own
        # minimumWidth above; belt-and-suspenders, since which one Qt
        # actually consults isn't consistent across widget/layout
        # combinations).
        grid_container.setMinimumWidth(
            CHANNELS_PER_ROW * ChannelCard.MIN_WIDTH + (CHANNELS_PER_ROW - 1) * 8 + 16
        )
        self.grid = QGridLayout(grid_container)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.grid.setSpacing(8)
        # No blanket AlignLeft|AlignTop on the layout itself - that
        # pins it to its own minimum content size and dumps ALL leftover
        # space (a bigger window than the 16 cards strictly need) as one
        # blank margin, instead of letting column/row stretch actually
        # grow the cards into it (see _reflow_grid()).
        scroll.setWidget(grid_container)
        return scroll

    def _on_uptime_changed(self, seconds: int):
        self.title_bar.set_uptime(f"Uptime {format_uptime(seconds)}")

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
        path = resolve_app_icon_path()
        if path is None:
            return
        icon = QIcon(path)
        QApplication.instance().setWindowIcon(icon)
        self.setWindowIcon(icon)
        self.title_bar.set_icon(icon)
        self.brand_mark_icon.refresh(path)

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
            # No alignment override: a card's own Expanding size policy
            # plus its maximumWidth/maximumHeight cap (ChannelCard.
            # MAX_WIDTH/MAX_HEIGHT) is what makes it actually grow to
            # fill a stretched column/row - forcing AlignLeft|AlignTop
            # here would pin it back to its natural size and dump the
            # stretched cell's extra space as blank margin beside it,
            # the same "big gutter" bug this grid used to have, just
            # spread across every cell instead of one lump on the right.
            self.grid.addWidget(self._cards[address], row, col)
        for col in range(CHANNELS_PER_ROW):
            self.grid.setColumnStretch(col, 1)
        for row in range((len(self._cards) + CHANNELS_PER_ROW - 1) // CHANNELS_PER_ROW):
            self.grid.setRowStretch(row, 1)

    def closeEvent(self, event):
        self.app.shutdown()
        event.accept()

    def _on_close_app_clicked(self):
        choice = CloseConfirmDialog.ask(self)
        if choice is None:
            return
        if choice == "turn_on":
            self._turn_on_all_and_close()
        else:
            self.close()

    def _turn_on_all_and_close(self):
        # "Turn On and Close" - a deliberate, manual user click, same as
        # every other manual ON action in this app (a channel card's own
        # toggle, Bulk Actions ON, SummaryPanel's Reset to Default
        # button) - so this is NOT connection-probed the way
        # _try_launch_auto_power_on() below is. That probe exists only
        # because THAT trigger fires with no user action at all, purely
        # from the window existing - firing it blind would silently
        # claim every channel is on with nobody having asked. A button
        # someone actually clicked is a real, deliberate request, exactly
        # like every other manual control here, and gets the same
        # optimistic-apply-after-timeout treatment they all get.
        # Kill-switch-tripped channels skipped, matching Reset to
        # Default's own convention for an ON action.
        self._run_bulk_channel_action(
            "Turning channels on before closing…",
            lambda controller: controller.turn_output_on(),
            skip_if_tripped=True,
        )
        self.close()

    def _try_launch_auto_power_on(self):
        # Direct port of sdr_c's conn_on_connected_changed(): the first
        # time this session actually confirms a real hardware
        # connection, power every channel on with Pseudo Random Noise
        # automatically - so opening the app and having it connect is
        # enough on its own. Never fires blind: turn_output_on() has no
        # confirmed-response path (see use_channel.py's
        # _on_response_timeout()) - it applies ON "unconfirmed" after a
        # timeout even when _find_and_open_connection() never found a
        # real port at all, the exact same as a real send that just got
        # no reply. Calling it unconditionally would therefore show
        # every channel ON with zero hardware attached - probing for a
        # real connection FIRST and skipping entirely when none exists
        # is the fix. Unlike sdr_c's own background retry (which also
        # catches a connection that succeeds a few seconds late), this
        # only probes once at launch - if nothing answers, channels
        # just start off, same as a fresh install always has.
        from hooks.use_connection import ConnectionController

        probe = ConnectionController()
        baud = self.app.config.get("baud_rate", 115200)
        parity = self.app.config.get("parity", "N")
        data_bits = self.app.config.get("data_bits", 8)
        hardware_present = probe.connect("DLL", baud, parity, data_bits)
        probe.disconnect()
        if not hardware_present:
            return

        self._run_bulk_channel_action(
            "Activating channels…",
            lambda controller: controller.turn_output_on(),
            skip_if_tripped=True,
        )

    def _run_bulk_channel_action(self, title: str, action, skip_if_tripped: bool = False):
        # Waits for every channel's send to settle (busy_changed ->
        # False) before returning - firing the action and quitting
        # immediately would race AppController.shutdown()'s
        # channels.shutdown(), which cancels whatever's still pending.
        # ~16 channels serialized through one shared port scheduler
        # takes a few real seconds, so ResetProgressOverlay gives live
        # "N / 16" feedback instead of the window just looking frozen.
        total = len(self.app.channels.controllers)
        overlay = ResetProgressOverlay(self, title, total)
        done = 0
        pending = set(self.app.channels.controllers.keys())
        loop = QEventLoop()

        def _mark_done(address):
            nonlocal done
            pending.discard(address)
            done += 1
            overlay.set_progress(done)
            if not pending:
                loop.quit()

        def _on_busy_changed(address, busy):
            if not busy:
                _mark_done(address)

        connections = []
        for address, controller in self.app.channels.controllers.items():
            slot = lambda busy, addr=address: _on_busy_changed(addr, busy)
            controller.busy_changed.connect(slot)
            connections.append((controller, slot))
            if skip_if_tripped and not self.app.safety.allow_power_on(address):
                _mark_done(address)
            else:
                action(controller)

        if pending:
            loop.exec()

        for controller, slot in connections:
            controller.busy_changed.disconnect(slot)

        overlay.hide()
        overlay.deleteLater()
