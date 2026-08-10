from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget

from styles.theme_colors import TEXT_DARK, BORDER_SUBTLE


class LogsDialog(QDialog):
    """Bigger, resizable, scrollable view of the same TX/RX log the
    compact Logs card shows - the card only has room for a handful of
    visible lines at once; this is for scrolling back through the full
    history (see MainWindow.LOG_MAX_ENTRIES) at a comfortable size.
    A native window (not the app's frameless chrome) since QInputDialog
    (the Query flow) already uses native dialogs too."""

    def __init__(self, parent, lines: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Logs")
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {BORDER_SUBTLE}; font-size: 12px; color: {TEXT_DARK}; }}"
        )
        self.list.addItems(lines)
        self.list.scrollToBottom()
        layout.addWidget(self.list)

    def append_line(self, line: str, max_entries: int):
        self.list.addItem(line)
        while self.list.count() > max_entries:
            self.list.takeItem(0)
        self.list.scrollToBottom()
