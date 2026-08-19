from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal

from .card import Card
from styles.theme_colors import TEXT_MUTED, BORDER_SUBTLE, NAVY, ACCENT_BLUE


class ControlsBar(Card):

    query_requested = Signal()
    clear_log_requested = Signal()

    def __init__(self, min_width: int, parent=None):
        super().__init__("Controls", icon="fa5s.sliders-h", parent=parent)
        self.setMinimumWidth(min_width)

        status_row = QHBoxLayout()
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
