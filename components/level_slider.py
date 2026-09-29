from PySide6.QtWidgets import QSlider
from PySide6.QtCore import Qt

from styles import theme_colors


def _groove_background(value: int) -> str:
    # Built fresh per call, not as a module-level dict - theme_colors'
    # values would otherwise be frozen in at import time and go stale
    # after a theme toggle.
    t = theme_colors
    return {
        0: f"background: {t.NEUTRAL_TRACK};",
        1: (
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {t.NEUTRAL_TRACK}, stop:0.666 {t.NEUTRAL_TRACK}, "
            f"stop:0.667 {t.STATUS_OK}, stop:1 {t.STATUS_OK});"
        ),
        2: (
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {t.NEUTRAL_TRACK}, stop:0.333 {t.NEUTRAL_TRACK}, "
            f"stop:0.334 {t.WARNING_BORDER}, stop:1 {t.STATUS_OK});"
        ),
        3: (
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {t.STATUS_ERROR}, stop:0.5 {t.WARNING_BORDER}, stop:1 {t.STATUS_OK});"
        ),
    }[value]


def _handle_style() -> str:
    return f"""
    QSlider::handle:vertical {{
        width: 20px;
        height: 20px;
        margin: 0 -5px;
        border-radius: 10px;
        background: {theme_colors.SLIDER_HANDLE};
        border: 2px solid {theme_colors.ACCENT_BLUE};
    }}
    QSlider::handle:vertical:hover {{
        border: 2px solid {theme_colors.ACCENT_BLUE};
        background: {theme_colors.ACCENT_BLUE};
    }}
"""


class LevelSlider(QSlider):

    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.setRange(0, 3)
        self.setSingleStep(1)
        self.setPageStep(1)
        self.setTickInterval(1)
        self.setTickPosition(QSlider.NoTicks)
        self.setFixedWidth(26)
        self.setFixedHeight(68)
        self.valueChanged.connect(self._update_groove)
        self._update_groove(self.value())

    def setValue(self, value: int):
        super().setValue(value)
        self._update_groove(value)

    def _update_groove(self, value: int):
        self.setStyleSheet(f"""
            QSlider::groove:vertical {{
                width: 10px;
                border-radius: 5px;
                {_groove_background(value)}
            }}
            {_handle_style()}
        """)
