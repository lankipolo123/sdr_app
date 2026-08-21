import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON_ICO = os.path.join(ROOT, "assets", "icons", "app_icon.ico")
ASSETS_DIR = os.path.join(ROOT, "assets")
WEB_DIR = os.path.join(ROOT, "web")
MAIN_SCRIPT = os.path.join(ROOT, "main.py")
ENCRYPTED_ARCHIVE = os.path.join(ROOT, "app_encrypted.pyz")

UPX_DIR = os.environ.get("UPX_DIR")

ADD_DATA = [
    f"{ASSETS_DIR}{os.pathsep}assets",
    f"{WEB_DIR}{os.pathsep}web",
    f"{ENCRYPTED_ARCHIVE}{os.pathsep}.",
]

# main.py only ever reaches the rest of the app (app.py, hooks/,
# services/, state/, utils/) through a dynamic importlib.import_module()
# call - deliberate, so PyInstaller's static analysis never discovers or
# bundles that code as plain, decompilable bytecode (see crypto_loader.py/
# build_encrypt.py: it ships AES-encrypted instead, in app_encrypted.pyz).
# The cost: PyInstaller's usual automatic discovery (which normally finds
# every real import by walking the module graph from main.py) never runs
# on any of it either, so every third-party package AND stdlib submodule
# that code actually uses has to be listed explicitly here - confirmed
# one at a time against a real built-and-run onedir binary (not guessed).
#
# webview.platforms.winforms (pywebview's Windows backend) and clr/
# clr_loader (pythonnet - what that backend hosts the WebView2 control
# through) are real `import` statements inside webview/guilib.py's
# platform-selection branches, which PyInstaller's static analysis
# usually follows even across an untaken if-branch - but they're listed
# explicitly anyway rather than trusting that to hold across a pywebview
# update, since the failure mode (missing DLL at launch) is silent and
# expensive to chase without a Windows box to reproduce it on.
HIDDEN_IMPORTS = [
    "webview", "webview.platforms.winforms", "clr", "clr_loader",
    "logging.handlers", "configparser", "contextlib", "copy", "ctypes",
    "collections", "dataclasses", "json", "struct", "enum", "typing",
]


def main():
    if not os.path.exists(ICON_ICO):
        sys.exit(f"Missing icon: {ICON_ICO}")

    print("Encrypting app source ->", ENCRYPTED_ARCHIVE)
    subprocess.run([sys.executable, os.path.join(ROOT, "build_encrypt.py")], check=True, cwd=ROOT)

    args = [
        sys.executable, "-OO", "-m", "PyInstaller",
        MAIN_SCRIPT,
        "--name", "TX Controller",
        "--onedir",
        "--windowed",
        "--icon", ICON_ICO,
        "--noconfirm",
    ]
    for entry in ADD_DATA:
        args += ["--add-data", entry]
    for module in HIDDEN_IMPORTS:
        args += ["--hidden-import", module]
    if UPX_DIR:
        args += ["--upx-dir", UPX_DIR]
    print("Running:", " ".join(args))
    subprocess.run(args, check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
