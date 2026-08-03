from PySide6.QtWidgets import QPushButton

from styles.theme_colors import STATUS_OK, STATUS_ERROR, BORDER_SUBTLE


class PowerButton(QPushButton):
    """A checkable button whose label names the action it will perform:
    'Activate' when the channel is off (click to turn on), 'Power Off'
    when it's on (click to turn off). Same checkable-button API as any
    QPushButton (toggled signal, isChecked(), setChecked()), so it drops
    into the existing bidirectional sync logic exactly like the old
    ToggleSwitch did."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedHeight(28)
        self._restyle()
        self.toggled.connect(self._restyle)

    def setChecked(self, checked: bool):
        # Always restyle, even when signals are blocked during a
        # programmatic sync from the slider - otherwise the label gets
        # stuck showing the old action when blockSignals() suppresses
        # the toggled signal this normally relies on.
        super().setChecked(checked)
        self._restyle()

    def _restyle(self, *_):
        if self.isChecked():
            self.setText("Power Off")
            self.setStyleSheet(
                f"QPushButton {{ background: {STATUS_ERROR}; color: #FFFFFF; "
                f"border: none; border-radius: 5px; font-weight: 600; padding: 4px 0; }}"
            )
        else:
            self.setText("Activate")
            self.setStyleSheet(
                f"QPushButton {{ background: {STATUS_OK}; color: #FFFFFF; "
                f"border: none; border-radius: 5px; font-weight: 600; padding: 4px 0; }}"
            )
