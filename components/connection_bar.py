from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from .card import Card
from .combo_box import ComboBox
from styles.theme_colors import TEXT_MUTED, STATUS_OK, STATUS_ERROR, WARNING_BORDER


class ConnectionBar(Card):
    """Connection status card - icon badge, status dot + text, the actual
    port/baud being dialed shown as the 'target' line, and the functional
    controls (port dropdown, refresh, connect) underneath."""

    def __init__(self, connection_controller, config_service=None, parent=None):
        super().__init__("Connection", icon="fa5s.chart-bar")
        self.setMaximumWidth(320)
        self.conn = connection_controller
        self.config = config_service
        self.conn.connected_changed.connect(self._on_connected_changed)
        self.conn.error.connect(self._on_connection_error)

        status_row = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_text = QLabel("DISCONNECTED")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_text)
        status_row.addStretch()
        self.body_layout.addLayout(status_row)

        self.target_label = QLabel("Target: not set")
        self.target_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self.body_layout.addWidget(self.target_label)

        controls_row = QHBoxLayout()
        self.port_combo = ComboBox()
        self.refresh_btn = QPushButton("Refresh")
        self.connect_btn = QPushButton("Connect")
        controls_row.addWidget(QLabel("Port:"))
        controls_row.addWidget(self.port_combo)
        controls_row.addWidget(self.refresh_btn)
        controls_row.addWidget(self.connect_btn)
        controls_row.addStretch()
        self.body_layout.addLayout(controls_row)

        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self._on_connect_clicked)

        self.refresh_ports()
        self._on_connected_changed(self.conn.is_connected())

    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = self.conn.list_ports()
        self.port_combo.addItems(ports)
        if current in ports:
            self.port_combo.setCurrentText(current)

    def _on_connect_clicked(self):
        if self.conn.is_connected():
            self.conn.disconnect()
            return
        port = self.port_combo.currentText()
        if not port:
            return
        baud = self.config.get("baud_rate", 115200) if self.config else 115200
        parity = self.config.get("parity", "N") if self.config else "N"
        data_bits = self.config.get("data_bits", 8) if self.config else 8

        self._set_status("connecting", f"{port} @ {baud}")

        previous_port = self.config.get("com_port", "") if self.config else ""
        if self.config:
            self.config.set("com_port", port)
        if self.conn.connect(port, baud, parity, data_bits):
            if self.config:
                self.config.save()
        elif self.config:
            self.config.set("com_port", previous_port)

    def _on_connected_changed(self, connected: bool):
        port = self.config.get("com_port", "") if self.config else ""
        baud = self.config.get("baud_rate", 115200) if self.config else 115200
        target = f"{port} @ {baud}" if port else "not set"
        if connected:
            self._set_status("online", target)
            self.connect_btn.setText("Disconnect")
        else:
            self._set_status("disconnected", target)
            self.connect_btn.setText("Connect")

    def _on_connection_error(self, _message: str):
        if not self.conn.is_connected():
            port = self.config.get("com_port", "") if self.config else ""
            baud = self.config.get("baud_rate", 115200) if self.config else 115200
            self._set_status("disconnected", f"{port} @ {baud}" if port else "not set")

    def _set_status(self, state: str, target: str):
        colors = {
            "connecting": (WARNING_BORDER, "CONNECTING"),
            "online": (STATUS_OK, "ONLINE"),
            "disconnected": (STATUS_ERROR, "DISCONNECTED"),
        }
        color, text = colors[state]
        self.status_text.setText(text)
        self.status_text.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 12px;")
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.target_label.setText(f"Target: {target}")
