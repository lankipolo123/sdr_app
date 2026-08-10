from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget

from styles.theme_colors import TEXT_DARK, BORDER_SUBTLE


class LogsDialog(QDialog):
    """Bigger, resizable, scrollable view of the same TX/RX log the
    compact Logs card shows - the card only has room for a handful of
    visible lines at once; this is for scrolling back through the full
    history (see MainWindow.LOG_MAX_ENTRIES) at a comfortable size.
    A native window (not the app's frameless chrome) since QInputDialog
    (the Query flow) already uses native dialogs too - the OS's own
    title bar/resize border is the trade-off for real drag-to-resize,
    which an in-app overlay panel can't do without a lot more custom
    resize-handle code.

    Always built fresh from whatever the compact log currently holds
    (see MainWindow._on_open_logs_dialog) rather than kept around and
    reused - a reused instance only ever got backfilled once, at its
    first creation, so entries added while it was closed silently
    never made it in and reopening showed stale (sometimes empty)
    content."""

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
