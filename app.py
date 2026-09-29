import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from hooks import AppController
from pages.main_page import MainWindow
from styles import theme_colors
from styles.theme_colors import app_palette, build_global_qss
from utils.app_paths import resolve_app_icon_path


def run():
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")

    icon_path = resolve_app_icon_path()
    if icon_path is not None:
        qt_app.setWindowIcon(QIcon(icon_path))

    app_controller = AppController()
    # Restored before the first paint, not left at the module's dark
    # default - see MainWindow._on_theme_toggle_requested(), which is
    # the only other place this flips and the only place that persists it.
    theme_colors.set_light_mode(app_controller.config.get("light_mode", False))
    qt_app.setPalette(app_palette())
    qt_app.setStyleSheet(build_global_qss())

    window = MainWindow(app_controller)
    window.show()
    # Direct port of sdr_c's own launch behavior: a real, confirmed
    # hardware connection - never a blind assumption - is what powers
    # every channel on automatically. See
    # MainWindow._try_launch_auto_power_on()'s own comment for why this
    # can't just call turn_output_on() unconditionally. If that first
    # attempt doesn't find hardware right away (a real USB-enumeration
    # race, or it's just not plugged in yet), the background retry
    # keeps trying every 5s until it connects - see
    # start_launch_auto_power_on_retry()'s own comment.
    if not window._try_launch_auto_power_on():
        window.start_launch_auto_power_on_retry()

    sys.exit(qt_app.exec())
