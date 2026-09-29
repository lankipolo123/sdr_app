from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter

from styles import theme_colors

_OVERLAY_COLOR = QColor(31, 41, 55, 90)


class ResetProgressOverlay(QWidget):
    """Modal progress overlay shown while every channel is being reset to
    default (ON) - both at app open and at close (MainWindow's
    _reset_all_channels_to_default()). Both send up to 16 channels'
    worth of commands serially through one shared port scheduler (~5s
    total, see the timing note in that method), so this gives real-time
    "N / 16" feedback instead of the window looking frozen for that
    whole stretch - direct request, wired identically for open and
    close so both show the same live progression."""

    def __init__(self, parent, title: str, total: int):
        top_level = parent.window() if parent is not None else None
        super().__init__(top_level)
        self._total = total

        if top_level is not None:
            self.setGeometry(top_level.rect())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QLabel()
        panel.setObjectName("ResetProgressPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(320)
        panel.setStyleSheet(
            f"#ResetProgressPanel {{ background: {theme_colors.SURFACE}; border-radius: 12px; "
            f"border: 1px solid {theme_colors.BORDER_SUBTLE}; }}"
        )

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 20, 24, 20)
        panel_layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"color: {theme_colors.TEXT_DARK}; font-size: 15px; font-weight: 700; background: transparent;"
        )
        panel_layout.addWidget(title_label)

        self._count_label = QLabel(f"0 / {total}")
        self._count_label.setStyleSheet(
            f"color: {theme_colors.TEXT_MUTED}; font-size: 13px; background: transparent;"
        )
        panel_layout.addWidget(self._count_label)

        self._bar = QProgressBar()
        self._bar.setRange(0, max(total, 1))
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(8)
        self._bar.setStyleSheet(
            f"QProgressBar {{ background: {theme_colors.BORDER_SUBTLE}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {theme_colors.ACCENT_BLUE}; border-radius: 4px; }}"
        )
        panel_layout.addWidget(self._bar)

        outer.addStretch()
        center_row = QHBoxLayout()
        center_row.addStretch()
        center_row.addWidget(panel)
        center_row.addStretch()
        outer.addLayout(center_row)
        outer.addStretch()

        self.show()
        self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), _OVERLAY_COLOR)

    def set_progress(self, done: int):
        self._count_label.setText(f"{done} / {self._total}")
        self._bar.setValue(done)
