from PySide6.QtWidgets import QSplashScreen
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont
from PySide6.QtCore import Qt, QRectF

from styles.theme_colors import NAVY, ACCENT_BLUE, TEXT_LIGHT

_SIZE = (360, 220)
_RADIUS = 14


def build_splash(icon_path: str) -> QSplashScreen:
    width, height = _SIZE
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), _RADIUS, _RADIUS)
    painter.fillPath(path, QColor(NAVY))

    icon = QPixmap(icon_path)
    if not icon.isNull():
        icon = icon.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap((width - icon.width()) // 2, 40, icon)

    painter.setPen(QColor(ACCENT_BLUE))
    painter.setFont(QFont("Segoe UI", 15, QFont.Bold))
    painter.drawText(QRectF(0, 128, width, 28), Qt.AlignCenter, "TX Controller")

    painter.setPen(QColor(TEXT_LIGHT))
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(QRectF(0, 160, width, 22), Qt.AlignCenter, "Loading...")

    painter.end()

    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
    splash.setWindowFlag(Qt.FramelessWindowHint)
    splash.setAttribute(Qt.WA_TranslucentBackground)
    return splash
