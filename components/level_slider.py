from PySide6.QtWidgets import QSlider
from PySide6.QtCore import Qt

from styles.theme_colors import ACCENT_BLUE, STATUS_OK, WARNING_BORDER, STATUS_ERROR


class LevelSlider(QSlider):
    """4 discrete positions (L0-L3), not continuous. Position -> Power dB
    mapping lives in state/level_map.py, reusing the existing protocol's
    Power dropdown values.

    Vertical, like a mixing-console fader - min (off) at the bottom, max
    at the top, matching QSlider's own default vertical convention. The
    groove itself is a fixed green -> orange -> red gradient (low to
    high intensity) rather than a plain track, so the handle's position
    against that gradient reads as "how hot is this channel running"
    at a glance - the same green/red vocabulary STATUS_OK/STATUS_ERROR
    already use elsewhere for on/off state."""

    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.setRange(0, 3)
        self.setSingleStep(1)
        self.setPageStep(1)
        self.setTickInterval(1)
        self.setTickPosition(QSlider.NoTicks)
        self.setFixedWidth(32)
        self.setFixedHeight(150)
        self.setStyleSheet(f"""
            QSlider::groove:vertical {{
                width: 10px;
                border-radius: 5px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {STATUS_ERROR}, stop:0.5 {WARNING_BORDER}, stop:1 {STATUS_OK});
            }}
            QSlider::handle:vertical {{
                width: 22px;
                height: 22px;
                margin: 0 -6px;
                border-radius: 11px;
                background: #FFFFFF;
                border: 2px solid {ACCENT_BLUE};
            }}
            QSlider::handle:vertical:hover {{
                border: 2px solid {ACCENT_BLUE};
                background: {ACCENT_BLUE};
            }}
        """)
