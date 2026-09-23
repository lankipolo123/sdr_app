from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PySide6.QtCore import Qt, Signal

from .card import Card
from styles.theme_colors import TEXT_MUTED, NAVY, ACCENT_BLUE
from styles.thermal_color import temp_band_color


class SensorCard(Card):
    """Port select + connect/disconnect + rack-wide average reading for
    the amplifier temperature/humidity sensors - the per-bay detail
    lives in SensorHeatmap below this, same split as the React
    rewrite's Dashboard ("Amplifier Temperature (Avg)" card +
    "Sensor Heatmap" card)."""

    connect_requested = Signal(str)  # port name
    disconnect_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, min_width: int, parent=None):
        super().__init__("Amplifier Sensors", icon="broadcast-tower.png", parent=parent)
        self.setMinimumWidth(min_width)

        row = QHBoxLayout()
        row.setSpacing(4)

        self.port_combo = QComboBox()
        self.port_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(self.port_combo, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        row.addWidget(refresh_btn)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCursor(Qt.PointingHandCursor)
        self.connect_btn.setStyleSheet(
            f"QPushButton {{ background: {NAVY}; border: 1px solid {NAVY}; "
            f"border-radius: 5px; font-size: 11px; padding: 4px 10px; color: {ACCENT_BLUE}; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE}; color: {NAVY}; }}"
        )
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        row.addWidget(self.connect_btn)
        self.body_layout.addLayout(row)

        self.avg_label = QLabel("Avg: -")
        self.avg_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 600;")
        self.body_layout.addWidget(self.avg_label)

        self._connected = False

    def set_ports(self, ports: list[str], selected: str | None):
        self.port_combo.clear()
        if not ports:
            self.port_combo.addItem("No ports found")
            return
        self.port_combo.addItems(ports)
        if selected and selected in ports:
            self.port_combo.setCurrentText(selected)

    def set_connected(self, connected: bool):
        self._connected = connected
        self.connect_btn.setText("Disconnect" if connected else "Connect")

    def set_average_temperature(self, avg_c: float | None, bay_count: int, reading_count: int):
        if avg_c is None:
            self.avg_label.setText("Avg: -")
            self.avg_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 600;")
            return
        r, g, b = temp_band_color(avg_c)
        self.avg_label.setText(f"Avg: {avg_c:.1f}°C  ({reading_count}/{bay_count} bays)")
        self.avg_label.setStyleSheet(f"color: rgb({r},{g},{b}); font-size: 12px; font-weight: 600;")

    def _on_connect_clicked(self):
        if self._connected:
            self.disconnect_requested.emit()
        else:
            self.connect_requested.emit(self.port_combo.currentText())
