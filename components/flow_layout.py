from PySide6.QtCore import Qt, QPoint, QRect, QSize
from PySide6.QtWidgets import QLayout, QSizePolicy, QStyle


class FlowLayout(QLayout):
    """A left-to-right row of widgets that wraps overflow onto additional
    rows once the available width runs out, instead of shrinking or
    clipping them the way QHBoxLayout would. Each widget keeps whatever
    fixed size it was given (see e.g. Controls/Logs/Dev Logs in
    MainWindow) - what changes as the window narrows is how many of them
    fit per row, recomputed automatically via heightForWidth/setGeometry
    on every resize, no manual resizeEvent handling needed by the caller.

    Adapted from Qt's own "Flow Layout" example (upstream C++, ported
    here for PySide6)."""

    def __init__(self, parent=None, margin=0, h_spacing=-1, v_spacing=-1):
        super().__init__(parent)
        self._h_space = h_spacing
        self._v_space = v_spacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        if self._h_space >= 0:
            return self._h_space
        return self._smart_spacing(QStyle.PM_LayoutHorizontalSpacing)

    def verticalSpacing(self):
        if self._v_space >= 0:
            return self._v_space
        return self._smart_spacing(QStyle.PM_LayoutVerticalSpacing)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            h_space = self.horizontalSpacing()
            if h_space == -1:
                h_space = widget.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal
                )
            v_space = self.verticalSpacing()
            if v_space == -1:
                v_space = widget.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical
                )

            next_x = x + item.sizeHint().width() + h_space
            if next_x - h_space > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + v_space
                next_x = x + item.sizeHint().width() + h_space
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y() + margins.bottom()

    def _smart_spacing(self, pixel_metric):
        parent = self.parent()
        if parent is None:
            return -1
        if parent.isWidgetType():
            return parent.style().pixelMetric(pixel_metric, None, parent)
        return parent.spacing()
