from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QToolButton
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QIcon, QGuiApplication

from styles.theme_colors import TEXT_DARK, TEXT_MUTED, BORDER_SUBTLE, STATUS_ERROR, SURFACE

# Thin border reserved purely for edge/corner resize grabbing - the
# frameless window has no OS-drawn frame to grab, so this margin (kept
# free of any child widget) is what ResizableContainer hit-tests against.
# Kept >= WINDOW_RADIUS so the rounded corner's curve always falls inside
# this margin band, never under the (square-cornered) title bar/content.
RESIZE_MARGIN = 8

# Corner radius of the window's rounded outline.
WINDOW_RADIUS = 8


class _CaptionButton(QToolButton):
    """One title-bar caption button (minimize/maximize/restore/close-app),
    hand-drawn so it doesn't depend on any icon font having the right glyphs.

    There is deliberately no bare OS-style "X" - the close button uses a
    power-style glyph instead and always goes through the same
    confirm-before-exit flow as everything else that quits the app."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(46, 32)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.ArrowCursor)
        hover_bg = STATUS_ERROR if kind == "close_app" else "rgba(0, 0, 0, 20)"
        self.setStyleSheet(
            f"QToolButton {{ background: transparent; border: none; }}"
            f"QToolButton:hover {{ background: {hover_bg}; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = "#FFFFFF" if (self.kind == "close_app" and self.underMouse()) else TEXT_MUTED
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
            # power-style glyph: a broken ring + a vertical tick through
            # the gap - same idea as the fa5s.power-off icon used
            # elsewhere in the app, just hand-drawn to match its siblings.
            rect = QRectF(cx - s, cy - s + 1, s * 2, s * 2 - 1)
            painter.drawArc(rect, 105 * 16, 330 * 16)
            painter.drawLine(cx, cy - s - 1, cx, cy - 1)
        painter.end()


class TitleBar(QWidget):
    """Replaces the native OS title bar entirely - the window is created
    frameless and this widget is the only title bar the user ever sees,
    so it always matches the app's own theme instead of whatever color
    Windows happens to be using for its own chrome.

    Dragging moves the real window via QWindow.startSystemMove() (the
    OS's own move behavior - snapping etc. still works), rather than
    hand-rolled mouse-delta math.

    Three buttons only: minimize, full screen, and close app - there is no
    bare OS-style X. The caller is responsible for running the same
    confirm-before-exit flow it already uses elsewhere (see
    close_app_requested).
    """

    close_app_requested = Signal()

    def __init__(self, window, title: str, icon: QIcon | None = None, parent=None):
        super().__init__(parent)
        self._window = window
        self._restore_geometry = None

        self.setFixedHeight(32)
        self.setStyleSheet(f"background: {SURFACE};")

        # A separate 1px-tall strip below the content row, not a border on
        # the row itself - a border drawn "under" the icon/title labels
        # gets painted over by them (children always paint after their
        # parent in Qt, and once the app has a global stylesheet active,
        # plain QLabels get an opaque background fill too). Giving the
        # line its own row means nothing can ever sit on top of it.
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
        title_label.setStyleSheet(f"color: {TEXT_DARK}; font-size: 12px; font-weight: 600;")
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

        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background: {BORDER_SUBTLE};")
        outer.addWidget(separator)

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
    """The frameless window's central widget. Its layout leaves a thin
    RESIZE_MARGIN border around the title bar + content; mouse activity in
    that border (the only place with no child widget to swallow it) turns
    into a native OS resize via startSystemResize(), so edge/corner
    resizing keeps working without the window having an actual frame.

    Also draws the window's actual rounded outline - just corner
    rounding on the fill, no separate border stroke, so it doesn't read
    as a card "containing" the content. Requires the top-level window to
    have WA_TranslucentBackground set (see MainWindow), otherwise this
    rounded fill would sit inside a still-square, still-opaque window."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {SURFACE}; border-radius: {WINDOW_RADIUS}px;")

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
