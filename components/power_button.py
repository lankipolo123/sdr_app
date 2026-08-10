from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt, Signal

from styles.theme_colors import STATUS_OK, STATUS_ERROR, BORDER_SUBTLE, TEXT_MUTED


class PowerButton(QWidget):
    """Two explicit buttons, ON and OFF, side by side - not a single
    checkable toggle whose label used to swap between 'Activate'/'Power
    Off'. Each click sends exactly one command (Output ON or Output
    OFF), same simplicity as the standalone Query diagnostic's ON/OFF
    choice - no bundled slider-resume or guessed Signal Control
    alongside it. The currently-known state just highlights whichever
    button matches it.

    Exposes the same isChecked()/setChecked()/toggled() API the old
    checkable-button version did (plus a click() convenience that flips
    to the opposite of whatever's currently highlighted), so this drops
    into ChannelCard's existing bidirectional sync logic unchanged."""

    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.on_btn = QPushButton("ON")
        self.off_btn = QPushButton("OFF")
        for btn in (self.on_btn, self.off_btn):
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            layout.addWidget(btn)

        # Always fires - a click always sends its command, even if that
        # state is already the one highlighted (matches Query: it always
        # sends, it never checks "is this already the state").
        self.on_btn.clicked.connect(lambda: self._set(True))
        self.off_btn.clicked.connect(lambda: self._set(False))

        self._restyle()

    def _set(self, checked: bool):
        self._checked = checked
        self._restyle()
        self.toggled.emit(checked)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        # Programmatic-only sync (e.g. from a hardware state change) -
        # never sends anything, same as the old checkable button's
        # override.
        self._checked = checked
        self._restyle()

    def click(self):
        """Flips to whichever button isn't currently highlighted -
        matches a single checkable button's click() semantics for
        callers that don't care which explicit button fired."""
        (self.off_btn if self._checked else self.on_btn).click()

    def _restyle(self):
        active_on = (
            f"QPushButton {{ background: {STATUS_OK}; color: #FFFFFF; "
            f"border: none; border-radius: 5px; font-weight: 600; padding: 4px 0; }}"
        )
        active_off = (
            f"QPushButton {{ background: {STATUS_ERROR}; color: #FFFFFF; "
            f"border: none; border-radius: 5px; font-weight: 600; padding: 4px 0; }}"
        )
        inactive = (
            f"QPushButton {{ background: transparent; color: {TEXT_MUTED}; "
            f"border: 1px solid {BORDER_SUBTLE}; border-radius: 5px; font-weight: 600; padding: 4px 0; }}"
        )
        self.on_btn.setStyleSheet(active_on if self._checked else inactive)
        self.off_btn.setStyleSheet(active_off if not self._checked else inactive)
