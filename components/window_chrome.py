from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QToolButton
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor, QIcon, QGuiApplication, QRegion

from styles.theme_colors import (
    TEXT_MUTED, BORDER_SUBTLE, STATUS_ERROR, STATUS_ERROR_LIGHT,
    NAVY, ACCENT_BLUE, TEXT_LIGHT, SURFACE,
)

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
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.ArrowCursor)
        self.setStyleSheet("QToolButton { background: transparent; border: none; }")

    def paintEvent(self, event):
        # No super().paintEvent() call - that's what draws Fusion's
        # autoRaise hover panel (the misaligned box). Hovering only ever
        # changes the icon's own line color below, never a background.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.kind == "close_app":
            color = STATUS_ERROR_LIGHT if self.underMouse() else STATUS_ERROR
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
            # power-style glyph: a broken ring + a vertical tick through
            # the gap - same idea as the fa5s.power-off icon used
            # elsewhere in the app, just hand-drawn to match its siblings.
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

        # 32 for the content row (matches the caption buttons' own fixed
        # 32px height) + 2 for the border below it.
        self.setFixedHeight(34)
        self.setObjectName("TitleBar")
        # Required for a plain QWidget (not QFrame) to actually paint its
        # QSS background/border at all - without this the stylesheet below
        # is accepted but silently never drawn (same gotcha ResizableContainer
        # already works around the same way).
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Full border on all four sides. Top corners rounded to match the
        # window's own rounded top edge; bottom stays a straight line
        # where it meets the content below. NAVY fill (the app's own
        # primary/brand color, same one every other NAVY-filled control -
        # Clear Log, the mode dropdown, Confirm - already uses) instead of
        # plain white, self-colored border so the fill reads as one solid
        # bar rather than a swatch with a visible seam.
        self.setStyleSheet(
            f"#TitleBar {{ background: {NAVY}; "
            f"border: 2px solid {NAVY}; "
            f"border-top-left-radius: 10px; border-top-right-radius: 10px; }}"
        )

        # A separate strip for the bottom border, not a border on the row
        # itself - a border drawn "under" the icon/title labels gets
        # painted over by them (children always paint after their
        # parent in Qt, and once the app has a global stylesheet active,
        # plain QLabels get an opaque background fill too). Giving it its
        # own row means nothing can ever sit on top of it.
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
        # Secondary/accent color, same as the minimize/full-screen buttons
        # beside it - the app's established NAVY-fill/ACCENT_BLUE-content
        # pairing, everywhere else it's used (Clear Log, mode dropdown,
        # Confirm).
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
    """The frameless window's central widget - fills the window edge to
    edge (no inset margin), so the title bar and its separator line sit
    genuinely flush with the real window edges, not stopped short by a
    gap. Rounded corners are done with a mask (setMask in resizeEvent)
    that clips everything - background and all children - to the rounded
    shape, rather than relying on an inset margin to keep square-cornered
    children clear of the curve. Requires the top-level window to have
    WA_TranslucentBackground set (see MainWindow), so the clipped-away
    corner pixels read as transparent instead of a leftover square.

    Not resizable by dragging its edges - that needs empty space around
    the content for hit-testing, which is exactly the gap this trades
    away. Minimize / full screen / close (the title bar's three buttons)
    are the only window-size controls."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self.setAttribute(Qt.WA_StyledBackground, True)
        # #ResizableContainer scopes this to just this one widget - a
        # bare, selector-less setStyleSheet() cascades to every child
        # that doesn't set its own "border", which is exactly what
        # happened here: every card, label, and button in the app
        # picked up this border too instead of just the outer window
        # (the same class of bug the title bar's separator line hit
        # earlier, for the same reason).
        self.setObjectName("ResizableContainer")
        self.setStyleSheet(
            f"#ResizableContainer {{ background: {SURFACE}; border-radius: {WINDOW_RADIUS}px; "
            f"border: 2px solid {BORDER_SUBTLE}; }}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), WINDOW_RADIUS, WINDOW_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
