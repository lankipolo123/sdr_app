from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QComboBox, QSpinBox
from PySide6.QtCore import Signal

from .card import Card
from hooks.use_connection import ConnectionController
from services.protocol import commands


class ManualTestCard(Card):
    """Manual, one-off command sending to any port/address - for hardware
    bring-up and debugging. Owns its own ConnectionController, separate
    from any channel ChannelManager has discovered."""

    raw_tx = Signal(bytes)
    raw_rx = Signal(bytes)

    def __init__(self, parent=None):
        super().__init__("Manual Test", icon="fa5s.terminal")
        self.conn = ConnectionController()
        self.conn.raw_tx.connect(self.raw_tx.emit)
        self.conn.raw_rx.connect(self.raw_rx.emit)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        port_row.addWidget(self.port_combo, 1)
        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setFixedWidth(28)
        self.refresh_btn.setToolTip("Refresh port list")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.refresh_btn)
        self.body_layout.addLayout(port_row)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        self.body_layout.addWidget(self.connect_btn)

        addr_row = QHBoxLayout()
        addr_row.addWidget(QLabel("Address:"))
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(0, 199)
        addr_row.addWidget(self.addr_spin)
        addr_row.addStretch()
        self.body_layout.addLayout(addr_row)

        btn_row = QHBoxLayout()
        self.query_addr_btn = QPushButton("Query Address")
        self.query_addr_btn.setToolTip("Broadcast - only safe with one device on the line")
        self.query_addr_btn.clicked.connect(self._on_query_address)
        btn_row.addWidget(self.query_addr_btn)
        self.query_status_btn = QPushButton("Query Status")
        self.query_status_btn.clicked.connect(self._on_query_status)
        btn_row.addWidget(self.query_status_btn)
        self.body_layout.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        self.output_on_btn = QPushButton("Output ON")
        self.output_on_btn.clicked.connect(self._on_output_on)
        btn_row2.addWidget(self.output_on_btn)
        self.output_off_btn = QPushButton("Output OFF")
        self.output_off_btn.clicked.connect(self._on_output_off)
        btn_row2.addWidget(self.output_off_btn)
        self.body_layout.addLayout(btn_row2)

        self.refresh_ports()

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
            self.connect_btn.setText("Connect")
            return
        port = self.port_combo.currentText()
        if not port:
            return
        if self.conn.connect(port):
            self.connect_btn.setText("Disconnect")

    def _on_query_address(self):
        self.conn.send(commands.query_address())

    def _on_query_status(self):
        self.conn.send(commands.query_status(self.addr_spin.value()))

    def _on_output_on(self):
        self.conn.send(commands.output_on(self.addr_spin.value()))

    def _on_output_off(self):
        self.conn.send(commands.output_off(self.addr_spin.value()))
