from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtGui import QColor, QPainter

from styles.theme_colors import (
    DIALOG_BG, TEXT_DARK, TEXT_MUTED, ACCENT_BLUE, ACCENT_BLUE_DARK,
    STATUS_ERROR, BORDER_SUBTLE,
)

_OVERLAY_COLOR = QColor(31, 41, 55, 90)


class PasswordDialog(QWidget):
    """Modal password prompt, same overlay/panel style as ConfirmDialog -
    used to gate Continuous Wave mode (see CwAuth, ChannelCard._on_mode_set).
    confirm=True adds a second "confirm password" field for bootstrapping a
    new password; otherwise it's a single field for entering an existing
    one. An optional on_submit(password) -> (ok, error_message) lets the
    caller verify inline - on failure the dialog shows the error and stays
    open (fields cleared) instead of closing, so a wrong password doesn't
    require re-opening the whole flow.
    """

    def __init__(self, parent, title: str, message: str, confirm: bool = False,
                 ok_text: str = "Unlock", on_submit=None):
        top_level = parent.window() if parent is not None else None
        super().__init__(top_level)
        self._confirm = confirm
        self._on_submit = on_submit
        self._submitted_password = None
        self._loop = None

        if top_level is not None:
            self.setGeometry(top_level.rect())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QLabel()
        panel.setObjectName("PasswordPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(320)
        panel.setStyleSheet(
            f"#PasswordPanel {{ background: {DIALOG_BG}; border-radius: 12px; "
            f"border: 1px solid {BORDER_SUBTLE}; }}"
        )

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 20, 24, 20)
        panel_layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {TEXT_DARK}; font-size: 17px; font-weight: 700; background: transparent;"
        )
        panel_layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setMinimumWidth(272)
        message_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 13px; background: transparent;"
        )
        panel_layout.addWidget(message_label)

        field_style = (
            f"QLineEdit {{ background: white; color: {TEXT_DARK}; "
            f"border: 1px solid {BORDER_SUBTLE}; border-radius: 6px; padding: 6px 8px; }}"
            f"QLineEdit:focus {{ border-color: {ACCENT_BLUE}; }}"
        )

        self.password_field = QLineEdit()
        self.password_field.setEchoMode(QLineEdit.Password)
        self.password_field.setPlaceholderText("Password")
        self.password_field.setStyleSheet(field_style)
        self.password_field.returnPressed.connect(self._on_submit_clicked)
        panel_layout.addWidget(self.password_field)

        self.confirm_field = None
        if confirm:
            self.confirm_field = QLineEdit()
            self.confirm_field.setEchoMode(QLineEdit.Password)
            self.confirm_field.setPlaceholderText("Confirm password")
            self.confirm_field.setStyleSheet(field_style)
            self.confirm_field.returnPressed.connect(self._on_submit_clicked)
            panel_layout.addWidget(self.confirm_field)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(
            f"color: {STATUS_ERROR}; font-size: 12px; background: transparent;"
        )
        self.error_label.hide()
        panel_layout.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setMinimumSize(90, 32)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_DARK}; "
            f"border: 1px solid {BORDER_SUBTLE}; border-radius: 4px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ border-color: {TEXT_DARK}; }}"
        )
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton(ok_text)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setMinimumSize(90, 32)
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_BLUE}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {ACCENT_BLUE_DARK}; }}"
            f"QPushButton:pressed {{ background: {ACCENT_BLUE_DARK}; }}"
        )
        ok_btn.clicked.connect(self._on_submit_clicked)
        btn_row.addWidget(ok_btn)

        panel_layout.addLayout(btn_row)

        outer.addStretch()
        center_row = QHBoxLayout()
        center_row.addStretch()
        center_row.addWidget(panel)
        center_row.addStretch()
        outer.addLayout(center_row)
        outer.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        self.password_field.setFocus()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), _OVERLAY_COLOR)

    def _on_submit_clicked(self):
        password = self.password_field.text()
        if not password:
            self._show_error("Enter a password.")
            return
        if self._confirm and password != self.confirm_field.text():
            self._show_error("Passwords don't match.")
            return
        if self._on_submit is not None:
            ok, error = self._on_submit(password)
            if not ok:
                self._show_error(error or "That password doesn't match.")
                self.password_field.clear()
                if self.confirm_field is not None:
                    self.confirm_field.clear()
                self.password_field.setFocus()
                return
        self._submitted_password = password
        self._close()

    def _show_error(self, text: str):
        self.error_label.setText(text)
        self.error_label.show()

    def _on_cancel(self):
        self._close()

    def _close(self):
        self.hide()
        if self._loop is not None:
            self._loop.quit()

    @staticmethod
    def _run(dialog: "PasswordDialog") -> str | None:
        dialog.show()
        dialog.raise_()
        loop = QEventLoop()
        dialog._loop = loop
        loop.exec()
        password = dialog._submitted_password
        dialog.deleteLater()
        return password

    @staticmethod
    def ask(parent, title: str, message: str, ok_text: str = "Unlock", on_submit=None) -> str | None:
        dialog = PasswordDialog(parent, title, message, confirm=False, ok_text=ok_text, on_submit=on_submit)
        return PasswordDialog._run(dialog)

    @staticmethod
    def set_new(parent, title: str, message: str, ok_text: str = "Set Password") -> str | None:
        dialog = PasswordDialog(parent, title, message, confirm=True, ok_text=ok_text)
        return PasswordDialog._run(dialog)
