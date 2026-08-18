from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QToolButton
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor, QIcon, QGuiApplication, QRegion

from styles.theme_colors import (
    TEXT_MUTED, BORDER_SUBTLE, STATUS_ERROR_LIGHT,
    NAVY, ACCENT_BLUE, TEXT_LIGHT, SURFACE,
)

WINDOW_RADIUS = 8


class _CaptionButton(QToolButton):

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(46, 32)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.ArrowCursor)
        self.setStyleSheet("QToolButton { background: transparent; border: none; }")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.kind == "close_app":
            color = TEXT_LIGHT if self.underMouse() else STATUS_ERROR_LIGHT
        else:
            color = TEXT_LIGHT if self.underMouse() else ACCENT_BLUE
        pen = QPen(QColor(color))
        pen.setWidthF(1.3)
        painter.setPen(pen)

        cx, cy = self.width() // 2, self.height() // 2
        s = 5
        if self.kind == "minimize":
            painter.drawLine(cx - s, cy, cx + s, cy)
        elif self.kind == "maximize":
            painter.drawRect(cx - s, cy - s, s * 2, s * 2)
        elif self.kind == "restore":
            painter.drawRect(cx - s + 3, cy - s - 1, s * 2 - 3, s * 2 - 3)
            painter.drawRect(cx - s - 1, cy - s + 3, s * 2 - 3, s * 2 - 3)
        elif self.kind == "close_app":
            rect = QRectF(cx - s, cy - s + 1, s * 2, s * 2 - 1)
            painter.drawArc(rect, 105 * 16, 330 * 16)
            painter.drawLine(cx, cy - s - 1, cx, cy - 1)
        painter.end()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class TitleBar(QWidget):

    close_app_requested = Signal()

    def __init__(self, window, title: str, icon: QIcon | None = None, parent=None):
        super().__init__(parent)
        self._window = window
        self._restore_geometry = None

        self.setFixedHeight(34)
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#TitleBar {{ background: {NAVY}; "
            f"border: 2px solid {ACCENT_BLUE}; "
            f"border-top-left-radius: {WINDOW_RADIUS}px; border-top-right-radius: {WINDOW_RADIUS}px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(8)

        if icon is not None and not icon.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(16, 16))
            layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {ACCENT_BLUE}; font-size: 12px; font-weight: 600;")
        layout.addWidget(title_label)

        layout.addStretch()

        self.min_btn = _CaptionButton("minimize")
        self.max_btn = _CaptionButton("maximize")
        self.close_btn = _CaptionButton("close_app")
        self.min_btn.setToolTip("Minimize")
        self.max_btn.setToolTip("Full Screen")
        self.close_btn.setToolTip("Close App")
        self.min_btn.clicked.connect(self._window.showMinimized)
        self.max_btn.clicked.connect(self._toggle_maximize)
        self.close_btn.clicked.connect(self.close_app_requested.emit)
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            layout.addWidget(btn)

        outer.addWidget(row, 1)

    def _is_maximized(self) -> bool:
        return self._restore_geometry is not None

    def _toggle_maximize(self):
        if self._is_maximized():
            self._window.setGeometry(self._restore_geometry)
            self._restore_geometry = None
        else:
            self._restore_geometry = self._window.geometry()
            screen = self._window.screen() or QGuiApplication.primaryScreen()
            self._window.setGeometry(screen.availableGeometry())
        self.max_btn.kind = "restore" if self._is_maximized() else "maximize"
        self.max_btn.setToolTip("Restore" if self._is_maximized() else "Full Screen")
        self.max_btn.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_maximize()


class ResizableContainer(QWidget):

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("ResizableContainer")
        self.setStyleSheet(
            f"#ResizableContainer {{ background: {SURFACE}; border-radius: {WINDOW_RADIUS}px; "
            f"border: 2px solid {ACCENT_BLUE}; }}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), WINDOW_RADIUS, WINDOW_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
