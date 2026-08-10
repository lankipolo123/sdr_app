from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter

from styles.theme_colors import DIALOG_BG, TEXT_DARK, TEXT_MUTED, BORDER_SUBTLE

_OVERLAY_COLOR = QColor(31, 41, 55, 90)


class LogsDialog(QWidget):
    """Bigger, scrollable view of the same TX/RX log the compact Logs
    card shows - the card only has room for a handful of visible lines
    at once; this is for scrolling back through the full history (see
    MainWindow.LOG_MAX_ENTRIES) at a comfortable size.

    A dimmed full-window overlay with a centered panel, the same
    pattern ConfirmDialog already uses (see components/confirm_dialog.py)
    - not a separate top-level QDialog, which on some window managers
    draws its own unthemed native title bar (an ugly, inconsistent
    color unrelated to anything this app controls) - staying inside
    the app's own frameless chrome avoids that entirely.

    Always built fresh with whatever the compact log currently holds
    (see MainWindow._on_open_logs_dialog) rather than kept around and
    reused - a reused instance only ever got backfilled once, at its
    first creation, so entries added while it was closed silently
    never made it in and reopening showed stale (sometimes empty)
    content."""

    def __init__(self, parent, lines: list[str]):
        top_level = parent.window() if parent is not None else None
        super().__init__(top_level)
        if top_level is not None:
            self.setGeometry(top_level.rect())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QWidget()
        panel.setObjectName("LogsPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setFixedSize(700, 500)
        panel.setStyleSheet(
            f"#LogsPanel {{ background: {DIALOG_BG}; border-radius: 12px; "
            f"border: 1px solid {BORDER_SUBTLE}; }}"
        )

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 12, 16, 16)
        panel_layout.setSpacing(8)

        header_row = QHBoxLayout()
        title_label = QLabel("Logs")
        title_label.setStyleSheet(
            f"color: {TEXT_DARK}; font-size: 15px; font-weight: 700; background: transparent;"
        )
        header_row.addWidget(title_label)
        header_row.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; color: {TEXT_MUTED}; font-size: 13px; }}"
            f"QPushButton:hover {{ color: {TEXT_DARK}; }}"
        )
        close_btn.clicked.connect(self.hide)
        header_row.addWidget(close_btn)
        panel_layout.addLayout(header_row)

        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {BORDER_SUBTLE}; font-size: 12px; color: {TEXT_DARK}; }}"
        )
        self.list.addItems(lines)
        self.list.scrollToBottom()
        panel_layout.addWidget(self.list, 1)

        center_row = QHBoxLayout()
        center_row.addStretch()
        center_row.addWidget(panel)
        center_row.addStretch()
        outer.addStretch()
        outer.addLayout(center_row)
        outer.addStretch()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), _OVERLAY_COLOR)

    def append_line(self, line: str, max_entries: int):
        self.list.addItem(line)
        while self.list.count() > max_entries:
            self.list.takeItem(0)
        self.list.scrollToBottom()
