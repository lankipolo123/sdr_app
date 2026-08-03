from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
import qtawesome as qta

from styles.theme_colors import STATUS_ERROR, STATUS_ERROR_DARK

ICON_SIZE = 16


class EmergencyStopButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("EMERGENCY STOP", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(qta.icon("fa5s.power-off", color="#FFFFFF"))
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setFixedHeight(40)
        self.setStyleSheet(
            f"QPushButton {{ background: {STATUS_ERROR}; color: #FFFFFF; "
            f"border: none; border-radius: 6px; font-weight: 700; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {STATUS_ERROR_DARK}; }}"
            f"QPushButton:pressed {{ background: {STATUS_ERROR_DARK}; }}"
        )
