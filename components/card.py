import os
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from styles.theme_colors import TEXT_DARK, BORDER_SUBTLE, ACCENT_BLUE
from utils.app_paths import resource_path
from .icon_utils import tint_pixmap, standard_icon_pixmap

_ICON_SIZE = 15
_ASSET_DIR = resource_path("assets", "icons", "pages")


def _resolve_icon(icon, tint_color: str):
    if icon is None:
        return None
    if isinstance(icon, str):
        path = os.path.join(_ASSET_DIR, icon)
        if not os.path.exists(path):
            return None
        pixmap = QPixmap(path).scaled(
            _ICON_SIZE, _ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        return tint_pixmap(pixmap, tint_color)
    return standard_icon_pixmap(icon, _ICON_SIZE, tint_color)


class Card(QFrame):
    def __init__(self, title: str, icon=None, accent: str | None = None, parent=None):
        super().__init__(parent)
        accent = accent or ACCENT_BLUE
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("Card")
        self.setStyleSheet(
            f"#Card {{ background: #FFFFFF; border: 2px solid {BORDER_SUBTLE}; "
            f"border-radius: 10px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(7)
        pixmap = _resolve_icon(icon, accent)
        if pixmap is not None:
            icon_label = QLabel()
            icon_label.setPixmap(pixmap)
            icon_label.setStyleSheet("background: transparent;")
            header.addWidget(icon_label)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {TEXT_DARK}; font-weight: 700; font-size: 12px; background: transparent;"
        )
        header.addWidget(title_label)
        header.addStretch()
        self.header_layout = header
        outer.addLayout(header)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(7)
        outer.addLayout(self.body_layout)


def make_card(title: str, icon=None, accent: str | None = None) -> Card:
    return Card(title, icon=icon, accent=accent)