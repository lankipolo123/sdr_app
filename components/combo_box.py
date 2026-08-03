from PySide6.QtWidgets import QComboBox


class ComboBox(QComboBox):
    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        popup.move(self.mapToGlobal(self.rect().bottomLeft()))