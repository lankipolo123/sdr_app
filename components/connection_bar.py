from PySide6.QtWidgets import QHBoxLayout, QLabel
from PySide6.QtCore import QTimer

from .card import Card
from styles.theme_colors import TEXT_MUTED, STATUS_OK, STATUS_ERROR, TX_ACCENT, RX_ACCENT

BLINK_MS = 150


class ConnectionBar(Card):
    """Aggregate connection status. Each channel now gets its own
    dedicated serial port (the modules are point-to-point over RS422,
    not a shared bus - one module per port), so there's no single "the
    connection" to pick a port for or connect/disconnect anymore. This
    just reflects how many channels ChannelManager currently has live,
    driven entirely by its signals."""

    def __init__(self, channels_manager, parent=None):
        super().__init__("Connection", icon="fa5s.chart-bar")
        self.channels = channels_manager

        status_row = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_text = QLabel("NO DEVICES")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_text)
        status_row.addStretch()

        self.tx_label = QLabel("TX")
        self.rx_label = QLabel("RX")
        self._set_activity_style(self.tx_label, active=False)
        self._set_activity_style(self.rx_label, active=False)
        status_row.addWidget(self.tx_label)
        status_row.addWidget(self.rx_label)
        self.body_layout.addLayout(status_row)

        self._tx_timer = QTimer(self)
        self._tx_timer.setSingleShot(True)
        self._tx_timer.timeout.connect(lambda: self._set_activity_style(self.tx_label, False))
        self._rx_timer = QTimer(self)
        self._rx_timer.setSingleShot(True)
        self._rx_timer.timeout.connect(lambda: self._set_activity_style(self.rx_label, False))

        self.detail_label = QLabel("Scanning…")
        self.detail_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self.body_layout.addWidget(self.detail_label)

        self.channels.channel_added.connect(self._on_channel_added)
        self.channels.discovery_progress.connect(self._on_progress)
        self.channels.discovery_finished.connect(self._on_finished)
        self.channels.raw_tx.connect(lambda _addr, _data: self._flash(self.tx_label, self._tx_timer))
        self.channels.raw_rx.connect(lambda _addr, _data: self._flash(self.rx_label, self._rx_timer))
        self._set_status(False, "Not scanned yet.")

    def _flash(self, label: QLabel, timer: QTimer):
        self._set_activity_style(label, active=True)
        timer.start(BLINK_MS)

    def _set_activity_style(self, label: QLabel, active: bool):
        color = TX_ACCENT if label is self.tx_label else RX_ACCENT
        label.setStyleSheet(
            f"color: {'#FFFFFF' if active else TEXT_MUTED}; "
            f"background: {color if active else 'transparent'}; "
            f"font-size: 10px; font-weight: 700; padding: 1px 4px; border-radius: 3px;"
        )

    def _on_progress(self, current: int, total: int):
        connected = len(self.channels.states) > 0
        self._set_status(connected, f"Scanning… checked port {current}/{total}")

    def _on_channel_added(self, _address: int):
        self._set_status(True, f"{len(self.channels.states)} channel(s) connected.")

    def _on_finished(self):
        count = len(self.channels.states)
        detail = f"{count} channel(s) connected." if count else "No devices found. Check wiring and power."
        self._set_status(count > 0, detail)

    def _set_status(self, connected: bool, detail: str):
        color = STATUS_OK if connected else STATUS_ERROR
        self.status_text.setText("ONLINE" if connected else "NO DEVICES")
        self.status_text.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 12px;")
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.detail_label.setText(detail)
