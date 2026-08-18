import qtawesome as qta

from PySide6.QtWidgets import QListWidget, QPushButton
from PySide6.QtCore import Qt

from .card import Card
from .logs_dialog import LogsDialog
from styles.theme_colors import TEXT_DARK, BORDER_SUBTLE, ACCENT_BLUE

LOG_MAX_ENTRIES = 200


class LogsPanel(Card):

    def __init__(self, title: str, icon: str, min_width: int,
                 max_entries: int = LOG_MAX_ENTRIES, parent=None):
        super().__init__(title, icon=icon, parent=parent)
        self.setMinimumWidth(min_width)
        self._title = title
        self._max_entries = max_entries
        self._dialog: LogsDialog | None = None

        maximize_btn = QPushButton()
        maximize_btn.setIcon(qta.icon("fa5s.expand-alt", color=ACCENT_BLUE))
        maximize_btn.setFixedSize(20, 20)
        maximize_btn.setCursor(Qt.PointingHandCursor)
        maximize_btn.setToolTip(f"Open full scrollable {title.lower()}")
        maximize_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; }"
            f"QPushButton:hover {{ background: {BORDER_SUBTLE}; border-radius: 4px; }}"
        )
        maximize_btn.clicked.connect(self._open_dialog)
        self.header_layout.addWidget(maximize_btn)

        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ border: none; font-size: 11px; color: {TEXT_DARK}; }}"
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

    def _open_dialog(self):
        lines = [self.list.item(i).text() for i in range(self.list.count())]
        self._dialog = LogsDialog(self, lines, title=self._title)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
