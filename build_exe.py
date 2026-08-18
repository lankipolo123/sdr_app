import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON_ICO = os.path.join(ROOT, "assets", "icons", "app_icon.ico")
ASSETS_DIR = os.path.join(ROOT, "assets")
MAIN_SCRIPT = os.path.join(ROOT, "main.py")

UPX_DIR = os.environ.get("UPX_DIR")

ADD_DATA = f"{ASSETS_DIR}{os.pathsep}assets"

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
    "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtNetworkAuth", "PySide6.QtHttpServer",
    "PySide6.QtQuickControls2", "PySide6.QtQuickTest", "PySide6.QtSpatialAudio",
    "PySide6.QtGraphs", "PySide6.QtGraphsWidgets", "PySide6.QtQuick3DPhysics",
    "PySide6.QtVirtualKeyboard", "PySide6.QtTextToSpeech",
    "PySide6.QtTest",
]


def main():
    if not os.path.exists(ICON_ICO):
        sys.exit(f"Missing icon: {ICON_ICO}")

    args = [
        sys.executable, "-OO", "-m", "PyInstaller",
        MAIN_SCRIPT,
        "--name", "TX Controller",
        "--onedir",
        "--windowed",
        "--icon", ICON_ICO,
        "--add-data", ADD_DATA,
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
