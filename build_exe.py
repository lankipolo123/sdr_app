"""Builds the standalone Windows .exe with PyInstaller.

Run this ON WINDOWS (PyInstaller builds for whatever OS it runs on -
there's no cross-compiling a Windows .exe from Linux/Mac). Needs
PyInstaller installed first:

    pip install pyinstaller

Then just:

    python build_exe.py

Output lands in dist/Noise Controller.exe - a single file, no console
window, with the app icon and the assets/ folder (icons) bundled
inside it. dist/, build/, and *.spec are all gitignored, so this
script (not a checked-in .spec file) is what stays reproducible in
version control.

SIZE: the app only ever imports PySide6.QtCore/QtGui/QtWidgets (QtTest
is dry_run.py's own dependency, not the shipped app's - confirmed by
grepping every "from PySide6." import in the codebase), but
PyInstaller's PySide6 hook bundles the ENTIRE Qt runtime by default -
QtWebEngine, Qml, Multimedia, Sql, Bluetooth, and a dozen others this
app never touches, easily 100+MB on its own. EXCLUDES below drops the
Python-level modules for all of those; --upx-dir additionally
compresses whatever binaries remain if UPX is installed (optional -
https://upx.github.io, unzip it anywhere and pass that folder's path
as UPX_DIR below or via the UPX_DIR env var - some antivirus engines
flag UPX-compressed executables as suspicious more often than
uncompressed ones, a real tradeoff to know about, not just a free
win). Actual before/after savings should be measured on a real build,
not assumed from this list alone - PyInstaller's own dependency
analysis can still pull in a plugin indirectly (e.g. a platform
integration DLL) despite an --exclude-module for its Python wrapper.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON_ICO = os.path.join(ROOT, "assets", "icons", "app_icon.ico")
ASSETS_DIR = os.path.join(ROOT, "assets")
MAIN_SCRIPT = os.path.join(ROOT, "main.py")

# Optional - set this to a real UPX install directory (or the UPX_DIR
# env var) to also compress the bundled binaries. None = skip UPX
# entirely, which is also PyInstaller's own default.
UPX_DIR = os.environ.get("UPX_DIR")

# PyInstaller wants SRC<sep>DEST for --add-data, and the separator is
# platform-specific (';' on Windows, ':' elsewhere) - os.pathsep gets
# this right without hardcoding a platform.
ADD_DATA = f"{ASSETS_DIR}{os.pathsep}assets"

# Qt modules this app never imports (see the module docstring above) -
# PySide6's own submodules, not third-party packages, so these are
# safe to drop regardless of what else is installed alongside PySide6.
UNUSED_QT_MODULES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSerialPort", "PySide6.QtSensors",
    "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets",  # app icons are .ico/qtawesome fonts, not .svg
    "PySide6.QtTest",  # dry_run.py's own dependency, not the shipped app's
]


def main():
    if not os.path.exists(ICON_ICO):
        sys.exit(f"Missing icon: {ICON_ICO}")

    args = [
        sys.executable, "-m", "PyInstaller",
        MAIN_SCRIPT,
        "--name", "Noise Controller",
        "--onefile",
        "--windowed",
        "--icon", ICON_ICO,
        "--add-data", ADD_DATA,
        # qtawesome ships its icon font/data as package resources -
        # PyInstaller's static import analysis doesn't see those (they're
        # loaded by qtawesome internally, not import-ed), so without this
        # they'd silently go missing from the bundle and every icon in
        # the app would just fail to render at runtime.
        "--collect-data", "qtawesome",
        "--noconfirm",
    ]
    for module in UNUSED_QT_MODULES:
        args += ["--exclude-module", module]
    if UPX_DIR:
        args += ["--upx-dir", UPX_DIR]
    print("Running:", " ".join(args))
    subprocess.run(args, check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
