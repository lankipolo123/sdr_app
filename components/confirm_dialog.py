from PySide6.QtWidgets import QMessageBox


class ConfirmDialog:

    @staticmethod
    def ask(parent, title: str, message: str,
            confirm_text: str = "Confirm", cancel_text: str = "Cancel",
            danger: bool = False) -> bool:
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
        confirm_btn = box.addButton(confirm_text, QMessageBox.AcceptRole)
        box.addButton(cancel_text, QMessageBox.RejectRole)
        box.setDefaultButton(confirm_btn)
        box.exec()
        return box.clickedButton() is confirm_btn
