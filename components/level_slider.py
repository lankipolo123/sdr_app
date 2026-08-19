from PySide6.QtWidgets import QSlider
from PySide6.QtCore import Qt


class LevelSlider(QSlider):

    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.setRange(0, 3)
        self.setSingleStep(1)
        self.setPageStep(1)
        self.setTickInterval(1)
        self.setTickPosition(QSlider.NoTicks)
        self.setFixedWidth(30)
        self.setFixedHeight(82)
