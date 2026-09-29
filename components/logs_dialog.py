from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget

from styles import theme_colors


class LogsDialog(QDialog):

    def __init__(self, parent, lines: list[str], title: str = "Logs"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {theme_colors.BORDER_SUBTLE}; font-size: 12px; color: {theme_colors.TEXT_DARK}; }}"
        )
        self.list.addItems(lines)
        self.list.scrollToBottom()
        layout.addWidget(self.list)

    def append_line(self, line: str, max_entries: int):
        self.list.addItem(line)
        while self.list.count() > max_entries:
            self.list.takeItem(0)
        self.list.scrollToBottom()
