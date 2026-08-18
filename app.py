import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from components import build_splash
from hooks import AppController
from pages.main_page import MainWindow
from styles.theme_colors import light_palette, build_global_qss
from utils.app_paths import resource_path

ICON_PATH = resource_path("assets", "icons", "app_icon.png")


def run():
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    qt_app.setPalette(light_palette())
    qt_app.setStyleSheet(build_global_qss())
    if os.path.exists(ICON_PATH):
        qt_app.setWindowIcon(QIcon(ICON_PATH))

    splash = build_splash(ICON_PATH)
    splash.show()
    qt_app.processEvents()

    app_controller = AppController()
    window = MainWindow(app_controller)
    window.show()
    splash.finish(window)

    sys.exit(qt_app.exec())
