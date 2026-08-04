from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QSpinBox
)
from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtGui import QColor, QPainter

from services.protocol.constants import ADDR_MIN, ADDR_MAX
from styles.theme_colors import (
    DIALOG_BG, TEXT_DARK, TEXT_MUTED, ACCENT_BLUE, ACCENT_BLUE_DARK, BORDER_SUBTLE,
)

_OVERLAY_COLOR = QColor(31, 41, 55, 90)


class ManualAddDialog(QWidget):
    """Add a channel by port + address directly, skipping Scan's
    broadcast entirely - only ever sends a targeted Status Query to the
    one address picked here. Exists to test whether a module actually
    answers when addressed directly while another module is still
    physically connected to the same converter, without touching
    anything already connected."""

    def __init__(self, parent, ports: list[str]):
        top_level = parent.window() if parent is not None else None
        super().__init__(top_level)
        self._result = None
        self._loop = None

        if top_level is not None:
            self.setGeometry(top_level.rect())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QWidget()
        panel.setObjectName("ManualAddPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(320)
        panel.setStyleSheet(
            f"#ManualAddPanel {{ background: {DIALOG_BG}; border-radius: 12px; "
            f"border: 1px solid {BORDER_SUBTLE}; }}"
        )

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 20, 24, 20)
        panel_layout.setSpacing(10)

        title_label = QLabel("Add by Address")
        title_label.setStyleSheet(
            f"color: {TEXT_DARK}; font-size: 17px; font-weight: 700; background: transparent;"
        )
        panel_layout.addWidget(title_label)

        message_label = QLabel(
            "Targets one address directly - no broadcast. Use this to try "
            "a specific module while another is still connected."
        )
        message_label.setWordWrap(True)
        message_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        panel_layout.addWidget(message_label)

        port_row = QHBoxLayout()
        port_label = QLabel("Port")
        port_label.setStyleSheet(f"color: {TEXT_DARK}; font-size: 13px; background: transparent;")
        port_row.addWidget(port_label)
        self.port_combo = QComboBox()
        self.port_combo.addItems(ports)
        port_row.addWidget(self.port_combo, 1)
        panel_layout.addLayout(port_row)

        addr_row = QHBoxLayout()
        addr_label = QLabel("Address")
        addr_label.setStyleSheet(f"color: {TEXT_DARK}; font-size: 13px; background: transparent;")
        addr_row.addWidget(addr_label)
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(ADDR_MIN, ADDR_MAX)
        addr_row.addWidget(self.addr_spin, 1)
        panel_layout.addLayout(addr_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setMinimumSize(90, 32)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_DARK}; "
            f"border: 1px solid {BORDER_SUBTLE}; border-radius: 4px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ border-color: {TEXT_DARK}; }}"
        )
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(cancel_btn)

        connect_btn = QPushButton("Connect")
        connect_btn.setCursor(Qt.PointingHandCursor)
        connect_btn.setMinimumSize(90, 32)
        connect_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_BLUE}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE_DARK}; }}"
            f"QPushButton:pressed {{ background: {ACCENT_BLUE_DARK}; }}"
        )
        connect_btn.setEnabled(bool(ports))
        connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(connect_btn)

        panel_layout.addLayout(btn_row)

        outer.addStretch()
        center_row = QHBoxLayout()
        center_row.addStretch()
        center_row.addWidget(panel)
        center_row.addStretch()
        outer.addLayout(center_row)
        outer.addStretch()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), _OVERLAY_COLOR)

    def _on_connect(self):
        self._result = (self.port_combo.currentText(), self.addr_spin.value())
        self._close()

    def _on_cancel(self):
        self._close()

    def _close(self):
        self.hide()
        if self._loop is not None:
            self._loop.quit()

    @staticmethod
    def ask(parent, ports: list[str]):
        """Returns (port, address) or None if cancelled / no ports available."""
        dialog = ManualAddDialog(parent, ports)
        dialog.show()
        dialog.raise_()
        loop = QEventLoop()
        dialog._loop = loop
        loop.exec()
        result = dialog._result
        dialog.deleteLater()
        return result
