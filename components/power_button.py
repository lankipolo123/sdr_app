from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt, Signal


class PowerButton(QWidget):

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
            btn.setFixedHeight(22)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            layout.addWidget(btn)

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
        self._checked = checked
        self._restyle()

    def click(self):
        (self.off_btn if self._checked else self.on_btn).click()

    def _restyle(self):
        self.on_btn.setChecked(self._checked)
        self.off_btn.setChecked(not self._checked)
