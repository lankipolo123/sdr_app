from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt

from styles import theme_colors


class KillSwitchBanner(QWidget):
    """Safety-critical, so shown globally regardless of which channel
    cards are visible - see hooks/use_safety.py for the 60C, manual-
    reset-only trip logic. Hidden entirely when nothing is tripped."""

    def __init__(self, app_controller, parent=None):
        super().__init__(parent)
        self.app = app_controller
        self.setObjectName("KillSwitchBanner")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#KillSwitchBanner {{ background: {theme_colors.WARNING_BG}; border-bottom: 1px solid {theme_colors.WARNING_BORDER}; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 6, 14, 6)

        self.message_label = QLabel()
        self.message_label.setStyleSheet(f"color: {theme_colors.WARNING_TEXT}; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.message_label, 1)

        reset_btn = QPushButton("Reset All")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setStyleSheet(
            f"QPushButton {{ background: {theme_colors.NAVY}; color: {theme_colors.ACCENT_BLUE}; border: 1px solid {theme_colors.NAVY}; "
            f"border-radius: 5px; font-size: 11px; font-weight: 600; padding: 4px 10px; }}"
        )
        reset_btn.clicked.connect(self.app.safety.reset_all)
        layout.addWidget(reset_btn)

        self.app.safety.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        tripped = self.app.safety.tripped_addresses()
        count = len(tripped)
        if count == 0:
            self.hide()
            return
        plural = "" if count == 1 else "s"
        self.message_label.setText(
            f"KILL SWITCH TRIPPED - {count} channel{plural} forced OFF. "
            f"Reset individual channels from their card, or reset all here."
        )
        self.show()
