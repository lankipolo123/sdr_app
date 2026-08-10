from PySide6.QtWidgets import QSlider
from PySide6.QtCore import Qt

from styles.theme_colors import ACCENT_BLUE, STATUS_OK, WARNING_BORDER, STATUS_ERROR, NEUTRAL_TRACK

# Per discrete level (0=off/bottom .. 3=max/top), the groove's own
# background - only the portion actually reached shows real color, the
# rest above it stays neutral gray. Defined per level directly rather
# than computed from a continuous fill fraction, since there are only
# ever 4 positions - a QSS gradient with two stops at the same position
# creates a hard edge instead of a blend, which is what makes the
# "not revealed yet" boundary sharp instead of fading into gray.
_GROOVE_BACKGROUNDS = {
    0: f"background: {NEUTRAL_TRACK};",
    1: (
        f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        f"stop:0 {NEUTRAL_TRACK}, stop:0.666 {NEUTRAL_TRACK}, "
        f"stop:0.667 {STATUS_OK}, stop:1 {STATUS_OK});"
    ),
    2: (
        f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        f"stop:0 {NEUTRAL_TRACK}, stop:0.333 {NEUTRAL_TRACK}, "
        f"stop:0.334 {WARNING_BORDER}, stop:1 {STATUS_OK});"
    ),
    3: (
        f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        f"stop:0 {STATUS_ERROR}, stop:0.5 {WARNING_BORDER}, stop:1 {STATUS_OK});"
    ),
}

_HANDLE_STYLE = f"""
    QSlider::handle:vertical {{
        width: 18px;
        height: 18px;
        margin: 0 -5px;
        border-radius: 9px;
        background: #FFFFFF;
        border: 2px solid {ACCENT_BLUE};
    }}
    QSlider::handle:vertical:hover {{
        border: 2px solid {ACCENT_BLUE};
        background: {ACCENT_BLUE};
    }}
"""


class LevelSlider(QSlider):
    """4 discrete positions (L0-L3), not continuous. Position -> Power dB
    mapping lives in state/level_map.py, reusing the existing protocol's
    Power dropdown values.

    Vertical, like a mixing-console fader - min (off) at the bottom, max
    at the top, matching QSlider's own default vertical convention. The
    groove's green -> orange -> red gradient (same green/red vocabulary
    STATUS_OK/STATUS_ERROR already use elsewhere for on/off state) only
    reveals up to the current level - at rest (L0) the whole track is
    neutral gray, and orange/red only become visible once the handle has
    actually been moved up into them, not sitting there permanently
    regardless of position. Manages its own stylesheet on value changes
    (see _update_groove) rather than relying on QSS add-page/sub-page
    layering, which didn't reliably mask the groove in practice."""

    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.setRange(0, 3)
        self.setSingleStep(1)
        self.setPageStep(1)
        self.setTickInterval(1)
        self.setTickPosition(QSlider.NoTicks)
        self.setFixedWidth(26)
        self.setFixedHeight(70)
        # QAbstractSlider.setValue() is a plain slot, not a virtual C++
        # method - when the user actually drags the handle, Qt's own
        # internal mouse handling changes the value without ever calling
        # back through this class's setValue() override below, so relying
        # on that override alone leaves the groove stuck on whatever level
        # it was last set to *programmatically* while the handle itself
        # visibly moves. valueChanged, in contrast, is a real signal that
        # Qt emits from its internal code too, so connecting to it is what
        # actually catches a live drag.
        self.valueChanged.connect(self._update_groove)
        self._update_groove(self.value())

    def setValue(self, value: int):
        # Still needed alongside the valueChanged connection above: when
        # ChannelCard reactively syncs this slider from real hardware
        # state, it wraps the setValue() call in blockSignals(True) to
        # avoid re-triggering a redundant hardware command - which also
        # suppresses valueChanged, so the connection above never fires for
        # that path. Overriding setValue() directly and calling
        # _update_groove() unconditionally covers that blocked-signal case.
        super().setValue(value)
        self._update_groove(value)

    def _update_groove(self, value: int):
        groove_bg = _GROOVE_BACKGROUNDS[value]
        self.setStyleSheet(f"""
            QSlider::groove:vertical {{
                width: 8px;
                border-radius: 4px;
                {groove_bg}
            }}
            {_HANDLE_STYLE}
        """)
