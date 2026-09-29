from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtGui import QColor, QPainter

from styles import theme_colors

_OVERLAY_COLOR = QColor(31, 41, 55, 90)


class CloseConfirmDialog(QWidget):
    """3 close choices: "Turn On and Close" (default - commands every
    channel on with Pseudo Random Noise for real, kill-switch-tripped
    channels skipped, same as SummaryPanel's Reset to Default button -
    direct app-specific request, not sdr_c's own on_app_close_shutdown()
    which turns off instead), "Keep Running and Close" (saves state,
    sends nothing - whatever's transmitting keeps transmitting after
    the app exits, matches sdr_c's on_close_keep_running()), "Cancel"
    (stays open). Channel state is saved to channels.ini either way by
    AppController.shutdown(), so that isn't a 4th choice."""

    def __init__(self, parent):
        top_level = parent.window() if parent is not None else None
        super().__init__(top_level)
        self._choice = None
        self._loop = None

        if top_level is not None:
            self.setGeometry(top_level.rect())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QLabel()
        panel.setObjectName("CloseConfirmPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setMinimumWidth(340)
        panel.setMaximumWidth(340)
        panel.setStyleSheet(
            f"#CloseConfirmPanel {{ background: {theme_colors.SURFACE}; border-radius: 12px; "
            f"border: 1px solid {theme_colors.BORDER_SUBTLE}; }}"
        )

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 20, 24, 20)
        panel_layout.setSpacing(10)

        title_label = QLabel("Close the app?")
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"color: {theme_colors.TEXT_DARK}; font-size: 17px; font-weight: 700; background: transparent;"
        )
        panel_layout.addWidget(title_label)

        message_label = QLabel(
            "Every channel's state is saved either way. Choose what happens "
            "to them before the app closes."
        )
        message_label.setWordWrap(True)
        message_label.setMinimumWidth(292)
        message_label.setStyleSheet(
            f"color: {theme_colors.TEXT_MUTED}; font-size: 13px; background: transparent;"
        )
        panel_layout.addWidget(message_label)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(8)

        turn_on_btn = QPushButton("Turn On and Close")
        turn_on_btn.setCursor(Qt.PointingHandCursor)
        turn_on_btn.setMinimumHeight(32)
        turn_on_btn.setStyleSheet(
            f"QPushButton {{ background: {theme_colors.STATUS_OK}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {theme_colors.STATUS_OK_DARK}; }}"
            f"QPushButton:pressed {{ background: {theme_colors.STATUS_OK_DARK}; }}"
        )
        turn_on_btn.clicked.connect(self._on_turn_on)
        btn_col.addWidget(turn_on_btn)

        keep_running_btn = QPushButton("Keep Running and Close")
        keep_running_btn.setCursor(Qt.PointingHandCursor)
        keep_running_btn.setMinimumHeight(32)
        keep_running_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme_colors.TEXT_DARK}; "
            f"border: 1px solid {theme_colors.BORDER_SUBTLE}; border-radius: 4px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ border-color: {theme_colors.ACCENT_BLUE}; color: {theme_colors.ACCENT_BLUE_DARK}; }}"
        )
        keep_running_btn.clicked.connect(self._on_keep_running)
        btn_col.addWidget(keep_running_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setMinimumHeight(32)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme_colors.TEXT_MUTED}; "
            f"border: 1px solid {theme_colors.BORDER_SUBTLE}; border-radius: 4px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ border-color: {theme_colors.TEXT_DARK}; color: {theme_colors.TEXT_DARK}; }}"
        )
        cancel_btn.clicked.connect(self._on_cancel)
        btn_col.addWidget(cancel_btn)

        panel_layout.addLayout(btn_col)

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

    def _on_turn_on(self):
        self._choice = "turn_on"
        self._close()

    def _on_keep_running(self):
        self._choice = "keep_running"
        self._close()

    def _on_cancel(self):
        self._close()

    def _close(self):
        self.hide()
        if self._loop is not None:
            self._loop.quit()

    @staticmethod
    def ask(parent) -> str | None:
        """Returns "turn_on", "keep_running", or None (Cancel)."""
        dialog = CloseConfirmDialog(parent)
        dialog.show()
        dialog.raise_()
        loop = QEventLoop()
        dialog._loop = loop
        loop.exec()
        choice = dialog._choice
        dialog.deleteLater()
        return choice
