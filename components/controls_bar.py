from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal

from .card import Card
from styles.theme_colors import TEXT_MUTED, BORDER_SUBTLE, NAVY, ACCENT_BLUE


class ControlsBar(Card):

    query_requested = Signal()
    clear_log_requested = Signal()
    load_config_requested = Signal()
    save_config_requested = Signal()

    def __init__(self, min_width: int, parent=None):
        super().__init__("Controls", icon="sliders-h.png", parent=parent)
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

        load_config_btn = QPushButton("Load Config")
        load_config_btn.setToolTip(
            "Apply a saved channels.ini back onto every channel for real "
            "(kill switch still applies - a tripped channel is skipped)"
        )
        load_config_btn.setCursor(Qt.PointingHandCursor)
        load_config_btn.setStyleSheet(
            f"QPushButton {{ background: {NAVY}; border: 1px solid {NAVY}; "
            f"border-radius: 5px; font-size: 11px; padding: 4px 10px; color: {ACCENT_BLUE}; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE}; color: {NAVY}; }}"
        )
        load_config_btn.clicked.connect(self.load_config_requested.emit)
        status_row.addWidget(load_config_btn)

        save_config_btn = QPushButton("Save Config")
        save_config_btn.setToolTip("Save every channel's current state to a channels.ini file you pick")
        save_config_btn.setCursor(Qt.PointingHandCursor)
        save_config_btn.setStyleSheet(
            f"QPushButton {{ background: {NAVY}; border: 1px solid {NAVY}; "
            f"border-radius: 5px; font-size: 11px; padding: 4px 10px; color: {ACCENT_BLUE}; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE}; color: {NAVY}; }}"
        )
        save_config_btn.clicked.connect(self.save_config_requested.emit)
        status_row.addWidget(save_config_btn)

        self.body_layout.addLayout(status_row)

    def set_status(self, text: str):
        self.status_label.setText(text)
