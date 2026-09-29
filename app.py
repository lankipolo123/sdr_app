import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from hooks import AppController
from pages.main_page import MainWindow
from styles.theme_colors import app_palette, build_global_qss
from utils.app_paths import resolve_app_icon_path


def run():
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    qt_app.setPalette(app_palette())
    qt_app.setStyleSheet(build_global_qss())

    icon_path = resolve_app_icon_path()
    if icon_path is not None:
        qt_app.setWindowIcon(QIcon(icon_path))

    app_controller = AppController()
    window = MainWindow(app_controller)
    window.show()

    sys.exit(qt_app.exec())
