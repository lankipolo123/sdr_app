from PySide6.QtWidgets import QSlider
from PySide6.QtCore import Qt

from styles.theme_colors import ACCENT_BLUE, BORDER_SUBTLE, NEUTRAL_TRACK


class LevelSlider(QSlider):
    """3 discrete positions (Min/Med/Max), not continuous - no Off
    position, that's the toggle's job. Position -> hex power code
    mapping lives in state/level_map.py."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(1, 3)
        self.setSingleStep(1)
        self.setPageStep(1)
        self.setTickInterval(1)
        self.setTickPosition(QSlider.NoTicks)
        self.setFixedWidth(180)
        self.setFixedHeight(24)
        self.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 6px;
                border-radius: 3px;
                background: {NEUTRAL_TRACK};
            }}
            QSlider::sub-page:horizontal {{
                height: 6px;
                border-radius: 3px;
                background: {ACCENT_BLUE};
            }}
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
        """)
