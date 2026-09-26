from PySide6.QtWidgets import QSlider
from PySide6.QtCore import Qt

from styles.theme_colors import ACCENT_BLUE, STATUS_OK, WARNING_BORDER, STATUS_ERROR, NEUTRAL_TRACK

_GROOVE_BACKGROUNDS = {
    0: f"background: {NEUTRAL_TRACK};",
    1: (
        f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {NEUTRAL_TRACK}, stop:0.666 {NEUTRAL_TRACK}, "
        f"stop:0.667 {STATUS_OK}, stop:1 {STATUS_OK});"
    ),
    2: (
        f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {NEUTRAL_TRACK}, stop:0.333 {NEUTRAL_TRACK}, "
        f"stop:0.334 {WARNING_BORDER}, stop:1 {STATUS_OK});"
    ),
    3: (
        f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {STATUS_ERROR}, stop:0.5 {WARNING_BORDER}, stop:1 {STATUS_OK});"
    ),
}

_HANDLE_STYLE = f"""
    QSlider::handle:horizontal {{
        width: 18px;
        height: 18px;
        margin: -6px 0;
        border-radius: 9px;
        background: #FFFFFF;
        border: 2px solid {ACCENT_BLUE};
    }}
    QSlider::handle:horizontal:hover {{
        border: 2px solid {ACCENT_BLUE};
        background: {ACCENT_BLUE};
    }}
"""


class LevelSlider(QSlider):

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(0, 3)
        self.setSingleStep(1)
        self.setPageStep(1)
        self.setTickInterval(1)
        self.setTickPosition(QSlider.NoTicks)
        self.setFixedWidth(130)
        self.setFixedHeight(26)
        self.valueChanged.connect(self._update_groove)
        self._update_groove(self.value())

    def setValue(self, value: int):
        super().setValue(value)
        self._update_groove(value)

    def _update_groove(self, value: int):
        groove_bg = _GROOVE_BACKGROUNDS[value]
        self.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 8px;
                border-radius: 4px;
                {groove_bg}
            }}
            {_HANDLE_STYLE}
        """)
