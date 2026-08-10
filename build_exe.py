"""Builds the standalone Windows .exe with PyInstaller.

Run this ON WINDOWS (PyInstaller builds for whatever OS it runs on -
there's no cross-compiling a Windows .exe from Linux/Mac). Needs
PyInstaller installed first:

    pip install pyinstaller

Then just:

    python build_exe.py

Output lands in dist/TX Controller.exe - a single file, no console
window, with the app icon and the assets/ folder (icons) bundled
inside it. dist/, build/, and *.spec are all gitignored, so this
script (not a checked-in .spec file) is what stays reproducible in
version control.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON_ICO = os.path.join(ROOT, "assets", "icons", "app_icon.ico")
ASSETS_DIR = os.path.join(ROOT, "assets")
MAIN_SCRIPT = os.path.join(ROOT, "main.py")

# PyInstaller wants SRC<sep>DEST for --add-data, and the separator is
# platform-specific (';' on Windows, ':' elsewhere) - os.pathsep gets
# this right without hardcoding a platform.
ADD_DATA = f"{ASSETS_DIR}{os.pathsep}assets"


def main():
    if not os.path.exists(ICON_ICO):
        sys.exit(f"Missing icon: {ICON_ICO}")

    args = [
        sys.executable, "-m", "PyInstaller",
        MAIN_SCRIPT,
        "--name", "TX Controller",
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
    print("Running:", " ".join(args))
    subprocess.run(args, check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
