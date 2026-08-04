from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton

from .card import Card
from styles.theme_colors import TX_ACCENT, RX_ACCENT, TEXT_MUTED, BORDER_SUBTLE

MAX_LINES = 1000


class CommLogPanel(Card):
    """Raw TX/RX hex traffic, live - for hardware bring-up/debugging,
    not part of the customer-facing flow."""

    def __init__(self, parent=None):
        super().__init__("Communication Log", icon="fa5s.terminal")
        self.setMinimumHeight(220)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LINES)
        self.log_view.setStyleSheet(
            f"QPlainTextEdit {{ background: #0F172A; color: #E5E7EB; "
            f"font-family: Consolas, monospace; font-size: 11px; "
            f"border: 1px solid {BORDER_SUBTLE}; border-radius: 6px; }}"
        )
        self.body_layout.addWidget(self.log_view)

        clear_row = QHBoxLayout()
        clear_row.addStretch()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.log_view.clear)
        clear_row.addWidget(self.clear_btn)
        self.body_layout.addLayout(clear_row)

    def log(self, direction: str, label: str, data: bytes):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        color = TX_ACCENT if direction == "TX" else RX_ACCENT
        self.log_view.appendHtml(
            f'<span style="color:{TEXT_MUTED}">{ts}</span> '
            f'<span style="color:{color}; font-weight:600;">{direction}</span> '
            f'<span style="color:{TEXT_MUTED}">{label}</span> '
            f'<span>{data.hex(" ").upper()}</span>'
        )
