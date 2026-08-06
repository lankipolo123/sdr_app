from PySide6.QtWidgets import QHBoxLayout, QLabel

from .card import Card
from styles.theme_colors import TEXT_MUTED, STATUS_OK, STATUS_ERROR


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
        self.body_layout.addLayout(status_row)

        self.detail_label = QLabel("Scanning…")
        self.detail_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self.body_layout.addWidget(self.detail_label)

        self.channels.channel_added.connect(self._on_channel_event)
        self.channels.channel_online.connect(self._on_channel_event)
        self.channels.channel_offline.connect(self._on_channel_event)
        self.channels.discovery_progress.connect(self._on_progress)
        self.channels.discovery_finished.connect(self._on_finished)
        self._set_status(False, "Not scanned yet.")

    def _live_count(self) -> int:
        # All 16 channel slots exist in self.channels.states from launch
        # (see ChannelManager) - counting states would always read 16
        # regardless of what's actually connected. controllers[address]
        # is None for anything not currently live, so count those instead.
        return sum(1 for c in self.channels.controllers.values() if c is not None)

    def _on_progress(self, current: int, total: int):
        connected = self._live_count() > 0
        self._set_status(connected, f"Scanning… checked port {current}/{total}")

    def _on_channel_event(self, _address: int):
        count = self._live_count()
        self._set_status(count > 0, f"{count} channel(s) connected.")

    def _on_finished(self):
        count = self._live_count()
        detail = f"{count} channel(s) connected." if count else "No devices found. Check wiring and power."
        self._set_status(count > 0, detail)

    def _set_status(self, connected: bool, detail: str):
        color = STATUS_OK if connected else STATUS_ERROR
        self.status_text.setText("ONLINE" if connected else "NO DEVICES")
        self.status_text.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 12px;")
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.detail_label.setText(detail)
