from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QToolButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QIcon, QGuiApplication

from styles.theme_colors import TEXT_DARK, TEXT_MUTED, BORDER_SUBTLE, STATUS_ERROR, SURFACE

# Thin border reserved purely for edge/corner resize grabbing - the
# frameless window has no OS-drawn frame to grab, so this margin (kept
# free of any child widget) is what ResizableContainer hit-tests against.
RESIZE_MARGIN = 6


class _CaptionButton(QToolButton):
    """One Windows-style caption button (minimize/maximize/restore/close),
    hand-drawn so it doesn't depend on any icon font having the right glyphs."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(46, 32)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.ArrowCursor)
        hover_bg = STATUS_ERROR if kind == "close" else "rgba(0, 0, 0, 20)"
        self.setStyleSheet(
            f"QToolButton {{ background: transparent; border: none; }}"
            f"QToolButton:hover {{ background: {hover_bg}; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = "#FFFFFF" if (self.kind == "close" and self.underMouse()) else TEXT_MUTED
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
        elif self.kind == "close":
            painter.drawLine(cx - s, cy - s, cx + s, cy + s)
            painter.drawLine(cx - s, cy + s, cx + s, cy - s)
        painter.end()


class TitleBar(QWidget):
    """Replaces the native OS title bar entirely - the window is created
    frameless and this widget is the only title bar the user ever sees,
    so it always matches the app's own theme instead of whatever color
    Windows happens to be using for its own chrome.

    Dragging moves the real window via QWindow.startSystemMove() (the
    OS's own move behavior - snapping etc. still works), rather than
    hand-rolled mouse-delta math.
    """

    def __init__(self, window, title: str, icon: QIcon | None = None, parent=None):
        super().__init__(parent)
        self._window = window
        self._restore_geometry = None

        self.setFixedHeight(32)
        self.setStyleSheet(f"background: {SURFACE}; border-bottom: 1px solid {BORDER_SUBTLE};")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(8)

        if icon is not None and not icon.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(16, 16))
            layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {TEXT_DARK}; font-size: 12px; font-weight: 600;")
        layout.addWidget(title_label)

        layout.addStretch()

        self.min_btn = _CaptionButton("minimize")
        self.max_btn = _CaptionButton("maximize")
        self.close_btn = _CaptionButton("close")
        self.min_btn.clicked.connect(self._window.showMinimized)
        self.max_btn.clicked.connect(self._toggle_maximize)
        self.close_btn.clicked.connect(self._window.close)
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            layout.addWidget(btn)

    def _is_maximized(self) -> bool:
        return self._restore_geometry is not None

    def _toggle_maximize(self):
        # Deliberately not window.showMaximized(): a real OS maximize on a
        # frameless window is a well-known can of worms on Windows (the
        # window can end up drawn under the taskbar). Resizing to the
        # screen's *available* geometry gets the same visual result
        # without touching native maximize at all.
        if self._is_maximized():
            self._window.setGeometry(self._restore_geometry)
            self._restore_geometry = None
        else:
            self._restore_geometry = self._window.geometry()
            screen = self._window.screen() or QGuiApplication.primaryScreen()
            self._window.setGeometry(screen.availableGeometry())
        self.max_btn.kind = "restore" if self._is_maximized() else "maximize"
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
    """The frameless window's central widget. Its layout leaves a thin
    RESIZE_MARGIN border around the title bar + content; mouse activity in
    that border (the only place with no child widget to swallow it) turns
    into a native OS resize via startSystemResize(), so edge/corner
    resizing keeps working without the window having an actual frame."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self.setMouseTracking(True)

    def _edges_at(self, pos):
        edges = Qt.Edges()
        if pos.x() <= RESIZE_MARGIN:
            edges |= Qt.LeftEdge
        elif pos.x() >= self.width() - RESIZE_MARGIN:
            edges |= Qt.RightEdge
        if pos.y() <= RESIZE_MARGIN:
            edges |= Qt.TopEdge
        elif pos.y() >= self.height() - RESIZE_MARGIN:
            edges |= Qt.BottomEdge
        return edges

    def _cursor_for(self, edges) -> Qt.CursorShape:
        left, right = bool(edges & Qt.LeftEdge), bool(edges & Qt.RightEdge)
        top, bottom = bool(edges & Qt.TopEdge), bool(edges & Qt.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.SizeBDiagCursor
        if left or right:
            return Qt.SizeHorCursor
        if top or bottom:
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def mouseMoveEvent(self, event):
        edges = self._edges_at(event.position().toPoint())
        self.setCursor(self._cursor_for(edges))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        edges = self._edges_at(event.position().toPoint())
        if edges and event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemResize(edges)
                event.accept()
                return
        super().mousePressEvent(event)

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)
