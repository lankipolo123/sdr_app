import os
import sys


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def user_data_dir() -> str:
    if is_frozen():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "Noise Controller")
    else:
        path = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(path, exist_ok=True)
    return path


def default_log_folder() -> str:
    return os.path.join(user_data_dir(), "logs") if is_frozen() else "logs"


def resource_path(*parts: str) -> str:
    """Path to a bundled READ-ONLY asset (icon, etc.) - resolves next
    to the running .exe when frozen, or the real project directory
    otherwise. sys._MEIPASS only exists under PyInstaller's --onefile
    mode (its temp self-extraction dir); this app builds --onedir, so
    that attribute is never actually set and the fallback -
    os.path.dirname(sys.executable), i.e. the app's own install folder
    - is what's really used. Kept as a fallback rather than removed in
    case the build ever switches back to --onefile.

    Deliberately separate from user_data_dir(): that one is for
    WRITABLE runtime files (config/logs), which must never live inside
    the app's own install folder (no write permission there for a
    per-machine install, and it'd vanish on uninstall/reinstall
    anyway)."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.join(os.path.dirname(__file__), "..")
    return os.path.join(base, *parts)
