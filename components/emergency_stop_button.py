from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
import qtawesome as qta

from styles.theme_colors import STATUS_ERROR, STATUS_ERROR_DARK

ICON_SIZE = 16


class EmergencyStopButton(QPushButton):
    def __init__(self, parent=None, icon_size: int = ICON_SIZE, font_size: int = 12):
        super().__init__("EMERGENCY STOP", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(qta.icon("fa5s.power-off", color="#FFFFFF"))
        self.setIconSize(QSize(icon_size, icon_size))
        self.setStyleSheet(
            f"QPushButton {{ background: {STATUS_ERROR}; color: #FFFFFF; "
            f"border: none; border-radius: 6px; font-weight: 700; font-size: {font_size}px; }}"
            f"QPushButton:hover {{ background: {STATUS_ERROR_DARK}; }}"
            f"QPushButton:pressed {{ background: {STATUS_ERROR_DARK}; }}"
        )
