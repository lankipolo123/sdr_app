from PySide6.QtWidgets import QSplashScreen
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont
from PySide6.QtCore import Qt, QRectF

from styles.theme_colors import NAVY, ACCENT_BLUE, TEXT_LIGHT

_SIZE = (360, 220)
_RADIUS = 14


def build_splash(icon_path: str) -> QSplashScreen:
    """A static loading screen shown while AppController/MainWindow are
    being constructed (see app.py's run()) - both happen synchronously
    on the main thread before the Qt event loop even starts, so nothing
    can actually animate during that window (a real spinner would need
    threaded construction, a much bigger change than what showing a
    loading screen calls for). Matches the app's own NAVY/ACCENT_BLUE
    frameless-card look instead of Qt's plain default splash rectangle,
    drawn once onto a QPixmap rather than relying on a static image
    asset that would need to be kept in sync with the theme by hand."""
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
