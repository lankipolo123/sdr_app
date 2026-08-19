from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtGui import QColor, QPainter

from styles.theme_colors import (
    DIALOG_BG, TEXT_DARK, TEXT_MUTED, ACCENT_BLUE, ACCENT_BLUE_DARK,
    STATUS_ERROR, STATUS_ERROR_DARK, BORDER_SUBTLE,
)

_OVERLAY_COLOR = QColor(31, 41, 55, 90)


class ConfirmDialog(QWidget):
    def __init__(self, parent, title: str, message: str,
                 confirm_text: str = "Confirm", cancel_text: str = "Cancel",
                 danger: bool = False):
        top_level = parent.window() if parent is not None else None
        super().__init__(top_level)
        self._confirmed = False
        self._loop = None

        if top_level is not None:
            self.setGeometry(top_level.rect())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QLabel()
        panel.setObjectName("ConfirmPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setMinimumWidth(340)
        panel.setMaximumWidth(340)
        panel.setStyleSheet(
            f"#ConfirmPanel {{ background: {DIALOG_BG}; border-radius: 12px; "
            f"border: 1px solid {BORDER_SUBTLE}; }}"
        )

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 20, 24, 20)
        panel_layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {TEXT_DARK}; font-size: 17px; font-weight: 700; background: transparent;"
        )
        panel_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setMinimumWidth(292)
        message_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 13px; background: transparent;"
        )
        panel_layout.addWidget(message_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton(cancel_text)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setMinimumSize(90, 32)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_DARK}; "
            f"border: 1px solid {BORDER_SUBTLE}; border-radius: 4px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ border-color: {TEXT_DARK}; }}"
        )
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(cancel_btn)

        confirm_color = STATUS_ERROR if danger else ACCENT_BLUE
        confirm_hover_color = STATUS_ERROR_DARK if danger else ACCENT_BLUE_DARK
        confirm_btn = QPushButton(confirm_text)
        confirm_btn.setCursor(Qt.PointingHandCursor)
        confirm_btn.setMinimumSize(90, 32)
        confirm_btn.setStyleSheet(
            f"QPushButton {{ background: {confirm_color}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {confirm_hover_color}; }}"
            f"QPushButton:pressed {{ background: {confirm_hover_color}; }}"
        )
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

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

    def _on_confirm(self):
        self._confirmed = True
        self._close()

    def _on_cancel(self):
        self._close()

    def _close(self):
        self.hide()
        if self._loop is not None:
            self._loop.quit()

    @staticmethod
    def ask(parent, title: str, message: str,
            confirm_text: str = "Confirm", cancel_text: str = "Cancel",
            danger: bool = False) -> bool:
        dialog = ConfirmDialog(parent, title, message, confirm_text, cancel_text, danger)
        dialog.show()
        dialog.raise_()
        loop = QEventLoop()
        dialog._loop = loop
        loop.exec()
        confirmed = dialog._confirmed
        dialog.deleteLater()
        return confirmed
