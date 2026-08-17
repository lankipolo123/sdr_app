from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal

from .card import Card
from styles.theme_colors import TEXT_MUTED, BORDER_SUBTLE, NAVY, ACCENT_BLUE


class ControlsBar(Card):
    """Top status/actions card: a running status line, the Query
    diagnostic button, and Clear Log. Doesn't know what Query or Clear
    Log actually DO - it just emits a signal on each click and leaves
    the real behavior to whoever wires it up (see MainWindow), same as
    any other presentational component."""

    query_requested = Signal()
    clear_log_requested = Signal()

    def __init__(self, min_width: int, parent=None):
        super().__init__("Controls", icon="fa5s.sliders-h", parent=parent)
        self.setMinimumWidth(min_width)

        status_row = QHBoxLayout()
        # Every channel is live and blind-sendable the moment the app
        # launches - no Scan/+Addr step to wait on (see ChannelManager).
        # This label is just a running status line for the last action
        # taken (a blind-send in flight, a disconnect, etc).
        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        status_row.addWidget(self.status_label)
        status_row.addStretch()

        query_btn = QPushButton("Query")
        query_btn.setToolTip(
            "Diagnostic: ask one specific address directly, brute-force "
            "finding the port, and actually wait for and verify a real "
            "confirmed response (or report failure) - separate from the "
            "cards, which still send blind"
        )
        query_btn.setStyleSheet(f"QPushButton {{ border: 1px solid {BORDER_SUBTLE}; border-radius: 5px; }}")
        query_btn.clicked.connect(self.query_requested.emit)
        status_row.addWidget(query_btn)

        # Background/text match the app icon's own colors exactly (NAVY
        # #1F2937 background, ACCENT_BLUE #64AAFF text/glyph - checked
        # against the actual icon pixels).
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.setToolTip(
            "Erase the app's log file (logs/sdr_controller.log) and the "
            "TX/RX list above"
        )
        clear_log_btn.setCursor(Qt.PointingHandCursor)
        clear_log_btn.setStyleSheet(
            f"QPushButton {{ background: {NAVY}; border: 1px solid {NAVY}; "
            f"border-radius: 5px; font-size: 11px; padding: 4px 10px; color: {ACCENT_BLUE}; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE}; color: {NAVY}; }}"
        )
        clear_log_btn.clicked.connect(self.clear_log_requested.emit)
        status_row.addWidget(clear_log_btn)
        self.body_layout.addLayout(status_row)

    def set_status(self, text: str):
        self.status_label.setText(text)
