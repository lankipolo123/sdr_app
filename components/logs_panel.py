from PySide6.QtWidgets import QListWidget, QPushButton
from PySide6.QtCore import Qt

from .card import Card
from .logs_dialog import LogsDialog
from styles import theme_colors

LOG_MAX_ENTRIES = 200


def _header_btn_style() -> str:
    return f"QPushButton {{ border: 1px solid {theme_colors.BORDER_SUBTLE}; border-radius: 5px; padding: 2px 8px; font-size: 10px; }}"


class LogsPanel(Card):

    def __init__(self, title: str, icon: str, min_width: int,
                 max_entries: int = LOG_MAX_ENTRIES, parent=None):
        super().__init__(title, icon=icon, parent=parent)
        self.setMinimumWidth(min_width)
        self._title = title
        self._max_entries = max_entries
        self._dialog: LogsDialog | None = None

        clear_btn = QPushButton("Clear")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(_header_btn_style())
        clear_btn.clicked.connect(self.clear)
        self.header_layout.addWidget(clear_btn)

        view_full_btn = QPushButton("View Full")
        view_full_btn.setCursor(Qt.PointingHandCursor)
        view_full_btn.setStyleSheet(_header_btn_style())
        view_full_btn.clicked.connect(self.open_dialog)
        self.header_layout.addWidget(view_full_btn)

        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ border: none; font-size: 11px; color: {theme_colors.TEXT_DARK}; }}"
        )
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body_layout.addWidget(self.list)

    def append_line(self, line: str):
        self.list.addItem(line)
        while self.list.count() > self._max_entries:
            self.list.takeItem(0)
        self.list.scrollToBottom()
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.append_line(line, self._max_entries)

    def clear(self):
        self.list.clear()
        if self._dialog is not None:
            self._dialog.list.clear()

    def open_dialog(self):
        lines = [self.list.item(i).text() for i in range(self.list.count())]
        self._dialog = LogsDialog(self, lines, title=self._title)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
