from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox
)
from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtGui import QColor, QPainter

from services.protocol.constants import ADDR_MIN, ADDR_MAX
from styles.theme_colors import (
    DIALOG_BG, TEXT_DARK, TEXT_MUTED, ACCENT_BLUE, ACCENT_BLUE_DARK,
    STATUS_OK, STATUS_ERROR, BORDER_SUBTLE,
)

_OVERLAY_COLOR = QColor(31, 41, 55, 90)


class ManualAddDialog(QWidget):
    """Ask one specific address directly - skips Scan's broadcast
    Address Query stage entirely. Brute-force searches every available
    port itself (same as clicking a channel card), no port to pick.
    Stays open across multiple attempts: type an address, hit Ask, see
    the result right here, change the number, Ask again - only Close
    closes it."""

    def __init__(self, parent, channels_manager):
        top_level = parent.window() if parent is not None else None
        super().__init__(top_level)
        self.channels = channels_manager
        self._loop = None
        self._asking_address = None

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

        title_label = QLabel("Ask an Address")
        title_label.setStyleSheet(
            f"color: {TEXT_DARK}; font-size: 17px; font-weight: 700; background: transparent;"
        )
        panel_layout.addWidget(title_label)

        message_label = QLabel(
            "Sends straight to this one address, no broadcast - searches every "
            "available port itself. Stays open - just change the address and "
            "ask again to try another."
        )
        message_label.setWordWrap(True)
        message_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        panel_layout.addWidget(message_label)

        addr_row = QHBoxLayout()
        addr_label = QLabel("Address")
        addr_label.setStyleSheet(f"color: {TEXT_DARK}; font-size: 13px; background: transparent;")
        addr_row.addWidget(addr_label)
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(ADDR_MIN, ADDR_MAX)
        addr_row.addWidget(self.addr_spin, 1)
        panel_layout.addLayout(addr_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        panel_layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setMinimumSize(90, 32)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_DARK}; "
            f"border: 1px solid {BORDER_SUBTLE}; border-radius: 4px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ border-color: {TEXT_DARK}; }}"
        )
        close_btn.clicked.connect(self._close)
        btn_row.addWidget(close_btn)

        self.ask_btn = QPushButton("Ask")
        self.ask_btn.setCursor(Qt.PointingHandCursor)
        self.ask_btn.setMinimumSize(90, 32)
        self.ask_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_BLUE}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE_DARK}; }}"
            f"QPushButton:pressed {{ background: {ACCENT_BLUE_DARK}; }}"
        )
        self.ask_btn.clicked.connect(self._on_ask)
        btn_row.addWidget(self.ask_btn)

        panel_layout.addLayout(btn_row)

        outer.addStretch()
        center_row = QHBoxLayout()
        center_row.addStretch()
        center_row.addWidget(panel)
        center_row.addStretch()
        outer.addLayout(center_row)
        outer.addStretch()

        self.channels.channel_added.connect(self._on_found)
        self.channels.channel_online.connect(self._on_found)
        self.channels.command_timeout.connect(self._on_timeout_message)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), _OVERLAY_COLOR)

    def _on_ask(self):
        address = self.addr_spin.value()
        self._asking_address = address
        self.status_label.setText(f"Asking address {address}…")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        self.channels.add_manual_channel(address)

    def _on_found(self, address: int):
        if address != self._asking_address:
            return  # some other channel came online, not the one we just asked
        self.status_label.setText(f"Address {address} answered.")
        self.status_label.setStyleSheet(f"color: {STATUS_OK}; font-size: 12px; font-weight: 600; background: transparent;")

    def _on_timeout_message(self, message: str):
        # Only messages caused by this dialog's own ask are relevant here -
        # add_manual_channel's failure text always names the address it
        # was asking, so match on that rather than reacting to every
        # timeout in the whole app while this dialog happens to be open.
        if str(self._asking_address if self._asking_address is not None else "") in message and "No response" in message:
            self.status_label.setText(message)
            self.status_label.setStyleSheet(f"color: {STATUS_ERROR}; font-size: 12px; font-weight: 600; background: transparent;")

    def _close(self):
        self.channels.channel_added.disconnect(self._on_found)
        self.channels.channel_online.disconnect(self._on_found)
        self.channels.command_timeout.disconnect(self._on_timeout_message)
        self.hide()
        if self._loop is not None:
            self._loop.quit()

    @staticmethod
    def open(parent, channels_manager):
        """Blocks the caller until Close is clicked - the dialog itself
        stays interactive the whole time (Qt's event loop keeps running
        during exec()), so multiple Ask attempts happen without this
        static method returning in between."""
        dialog = ManualAddDialog(parent, channels_manager)
        dialog.show()
        dialog.raise_()
        loop = QEventLoop()
        dialog._loop = loop
        loop.exec()
        dialog.deleteLater()
