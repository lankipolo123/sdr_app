import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON_ICO = os.path.join(ROOT, "assets", "icons", "app_icon.ico")
ASSETS_DIR = os.path.join(ROOT, "assets")
MAIN_SCRIPT = os.path.join(ROOT, "main.py")
ENCRYPTED_ARCHIVE = os.path.join(ROOT, "app_encrypted.pyz")
SPEC_FILE = os.path.join(ROOT, "tx_controller.spec")

UPX_DIR = os.environ.get("UPX_DIR")

# UPX has a known history of corrupting Qt's platform plugin (qwindows.dll
# fails to load -> the app silently refuses to start, no error dialog) and
# the CPython/MSVC runtime DLLs - excluded from compression even when UPX
# is otherwise enabled, since the size win there isn't worth that risk.
UPX_EXCLUDE = ["qwindows.dll", "python3*.dll", "vcruntime*.dll"]

ADD_DATA = [
    f"{ASSETS_DIR}{os.pathsep}assets",
    f"{ENCRYPTED_ARCHIVE}{os.pathsep}.",
]

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

# main.py only ever reaches the rest of the app (app.py, hooks/,
# components/, pages/, services/, state/, styles/, utils/) through a
# dynamic importlib.import_module() call - deliberate, so PyInstaller's
# static analysis never discovers or bundles that code as plain,
# decompilable bytecode (see crypto_loader.py/build_encrypt.py: it ships
# AES-encrypted instead, in app_encrypted.pyz). The cost: PyInstaller's
# usual automatic discovery (which normally finds every real import by
# walking the module graph from main.py) never runs on any of it either,
# so every third-party package AND stdlib submodule that code actually
# uses has to be listed explicitly here - confirmed one at a time against
# a real built-and-run onedir binary (not guessed): PySide6 is genuinely
# third-party, the rest are stdlib submodules PyInstaller's default
# bundling doesn't include unless something in the discovered graph
# really imports them.
HIDDEN_IMPORTS = [
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "logging.handlers", "configparser", "contextlib", "copy", "ctypes",
    "collections", "dataclasses", "json", "struct", "enum", "typing",
]

# Set PRUNE_QT_EXTRAS=0 to skip prune_qt_extras() below entirely and get
# PyInstaller's untouched default collection - useful for bisecting a
# build/runtime problem against "is this pruning's fault".
PRUNE_QT_EXTRAS = os.environ.get("PRUNE_QT_EXTRAS", "1") != "0"

# ANGLE (software/GLES-via-DirectX) and ICU are pulled in unconditionally
# by PyInstaller's PySide6 hook on Windows - see hook-PySide6.py's
# collect_extra_binaries(), which always grabs these if present in the Qt
# install regardless of which Qt modules the app actually imports. This
# app is pure QWidgets with Fusion styling (app.py) - no QtQuick/QML, no
# QOpenGLWidget - so it never touches any of them. These are usually the
# single largest chunk of a PySide6 onedir build (opengl32sw.dll alone is
# commonly 15-25MB).
_PRUNE_BINARY_PREFIXES = (
    "libegl", "libglesv2", "d3dcompiler_", "opengl32sw",
    "icudt", "icuin", "icuuc",
)

# Qt plugin categories the QtGui/QtWidgets hooks always collect in full
# (every file in the folder, no filtering) that this app doesn't use:
# iconengines is for QtSvg-backed icons (QtSvg is excluded above),
# platforminputcontexts/platformthemes are Linux input-method/desktop-
# theme integration, generic is tablet/touch input, styles only ever held
# the native "windowsvista" style (the app force-sets Fusion in app.py,
# which QtWidgets builds in directly, not a plugin), and imageformats is
# for formats Qt doesn't handle natively - confirmed with a real
# QGuiApplication (see PR discussion) that PNG, the only format this app
# ever loads at runtime (icons, splash - all .png), decodes fine with
# zero imageformats plugins present: PNG/BMP/PBM/PGM/PPM/XBM/XPM are
# compiled directly into QtGui. Only .ico/.jpeg/.gif/.svg/etc need the
# plugin folder.
#
# `platforms` keeps only qwindows.dll - the real Windows backend. The
# other three plugins in that folder are alternate backends selected via
# the QT_QPA_PLATFORM env var, which nothing in the shipped app sets
# (only tests/dry_run.py does, for headless dev runs - not part of the
# frozen build: main.py never imports tests/, so PyInstaller's Analysis
# never sees it).
_PRUNE_PLUGIN_DIRS = ("iconengines", "platforminputcontexts", "platformthemes", "generic", "styles", "imageformats")
_PLATFORMS_KEEP = ("qwindows.dll",)

# Excluding a plugin folder above doesn't clean up shared libraries that
# ONLY existed to back a plugin in it - PyInstaller's Analysis resolves a
# plugin's own DLL dependencies before prune_qt_extras ever runs, so
# removing e.g. imageformats/qpdf.dll doesn't remove what qpdf.dll
# dragged in with it. Traced each one's real PE import table (pefile,
# against the actual PySide6 6.11.2 Windows wheel) to confirm every file
# below is now a genuine orphan - nothing this build actually keeps
# (Qt6Core/Gui/Widgets, qwindows.dll, the imageformats plugins that
# survive) imports any of them:
#   imageformats/qpdf.dll  -> Qt6Pdf.dll -> Qt6Network.dll
#   imageformats/qsvg.dll  -> Qt6Svg.dll
#   platforminputcontexts' virtual-keyboard plugin
#       -> Qt6VirtualKeyboard.dll -> Qt6Quick.dll, Qt6Qml.dll
#       -> Qt6Quick.dll -> Qt6QmlMeta.dll, Qt6QmlModels.dll, Qt6Network.dll,
#                          Qt6OpenGL.dll
#       -> Qt6QmlMeta.dll -> Qt6QmlWorkerScript.dll
# Together these ran ~23MB in the 6.11.2 wheel - the single biggest chunk
# pruning has found since the plugin-folder pass itself.
_PRUNE_ORPHANED_LIBS = (
    "qt6pdf.dll", "qt6svg.dll", "qt6network.dll", "qt6virtualkeyboard.dll",
    "qt6qml.dll", "qt6quick.dll", "qt6qmlmeta.dll", "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll", "qt6opengl.dll",
)


def prune_qt_extras(binaries, datas):
    """Drop ANGLE/ICU binaries, the unused Qt plugin folders above, their
    now-orphaned shared-library dependencies, and Qt's own translation
    files (qtbase_*.qm etc. for every locale Qt ships - dead weight since
    the app never loads a QTranslator) from a completed PyInstaller
    Analysis. Returns (binaries, datas) as TOCs."""
    from PyInstaller.building.datastruct import TOC

    def _keep_binary(entry):
        dest_name, _src, _typecode = entry
        parts = dest_name.replace(os.sep, "/").lower().split("/")
        basename = parts[-1]
        if basename.startswith(_PRUNE_BINARY_PREFIXES):
            return False
        if basename in _PRUNE_ORPHANED_LIBS:
            return False
        if "plugins" in parts:
            plugin_idx = parts.index("plugins") + 1
            if plugin_idx < len(parts):
                plugin_dir = parts[plugin_idx]
                if plugin_dir in _PRUNE_PLUGIN_DIRS:
                    return False
                if plugin_dir == "platforms" and basename not in _PLATFORMS_KEEP:
                    return False
        return True

    def _keep_data(entry):
        dest_name, _src, _typecode = entry
        parts = dest_name.replace(os.sep, "/").lower().split("/")
        return "translations" not in parts

    kept_binaries, kept_datas, dropped = [], [], []
    for entry in binaries:
        (kept_binaries if _keep_binary(entry) else dropped).append(entry)
    for entry in datas:
        (kept_datas if _keep_data(entry) else dropped).append(entry)

    dropped_bytes = 0
    for _dest, src, _typecode in dropped:
        try:
            dropped_bytes += os.path.getsize(src)
        except OSError:
            pass
    print(
        f"prune_qt_extras: dropped {len(dropped)} files "
        f"({dropped_bytes / 1_048_576:.1f} MiB) - set PRUNE_QT_EXTRAS=0 to disable"
    )

    return TOC(kept_binaries), TOC(kept_datas)


def main():
    if not os.path.exists(ICON_ICO):
        sys.exit(f"Missing icon: {ICON_ICO}")

    print("Encrypting app source ->", ENCRYPTED_ARCHIVE)
    subprocess.run([sys.executable, os.path.join(ROOT, "build_encrypt.py")], check=True, cwd=ROOT)

    args = [sys.executable, "-OO", "-m", "PyInstaller", SPEC_FILE, "--noconfirm"]
    if UPX_DIR:
        args += ["--upx-dir", UPX_DIR]
    print("Running:", " ".join(args))
    subprocess.run(args, check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
