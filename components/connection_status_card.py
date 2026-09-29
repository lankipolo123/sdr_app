from PySide6.QtWidgets import QLabel, QPushButton
from PySide6.QtCore import Qt, Signal

from .card import Card
from styles import theme_colors


class ConnectionStatusCard(Card):
    """RS422/channel-bus connection status - direct port of sdr_c's
    IDC_CONN_STATUS_LBL/IDC_CONNECT_BTN, which this app never actually
    had: every channel command already auto-connects per-send behind
    the scenes (see hooks/use_channel.py's _find_and_open_connection()),
    but nothing ever showed whether real hardware was actually there.
    No port dropdown, unlike SensorCard - the channel bus is always
    "DLL" (AutoConnectSDR()), matching sdr_c's own single Connect
    button with no port picker. The button here only re-checks status
    (MainWindow._probe_connection_status()) - it never fires the
    reset-to-default power-on itself, so clicking it to check status
    can't surprise you by blasting every channel back on."""

    connect_requested = Signal()

    def __init__(self, min_width: int, parent=None):
        super().__init__("Connection", icon="broadcast-tower.png", parent=parent)
        self.setMinimumWidth(min_width)

        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet(
            f"color: {theme_colors.STATUS_ERROR}; font-size: 12px; font-weight: 700;"
        )
        self.body_layout.addWidget(self.status_label)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCursor(Qt.PointingHandCursor)
        self.connect_btn.setStyleSheet(
            f"QPushButton {{ background: {theme_colors.NAVY}; border: 1px solid {theme_colors.NAVY}; "
            f"border-radius: 5px; font-size: 11px; padding: 3px 8px; color: {theme_colors.ACCENT_BLUE}; }}"
            f"QPushButton:hover {{ background: {theme_colors.ACCENT_BLUE}; color: {theme_colors.NAVY}; }}"
        )
        self.connect_btn.clicked.connect(self.connect_requested.emit)
        self.body_layout.addWidget(self.connect_btn)

    def set_connected(self, connected: bool):
        self.status_label.setText("Connected" if connected else "Disconnected")
        color = theme_colors.STATUS_OK if connected else theme_colors.STATUS_ERROR
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 700;")
