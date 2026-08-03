import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from hooks import AppController
from pages.main_page import MainWindow
from styles.theme_colors import light_palette, build_global_qss

ICON_PATH = os.path.join(os.path.dirname(__file__), "assets", "icons", "app_icon.png")


def run():
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    qt_app.setPalette(light_palette())
    qt_app.setStyleSheet(build_global_qss())
    if os.path.exists(ICON_PATH):
        qt_app.setWindowIcon(QIcon(ICON_PATH))

    app_controller = AppController()
    window = MainWindow(app_controller)
    window.show()

    sys.exit(qt_app.exec())
