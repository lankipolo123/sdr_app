import os
import sys


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def user_data_dir() -> str:
    if is_frozen():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "TX Controller")
    else:
        path = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(path, exist_ok=True)
    return path


def default_log_folder() -> str:
    return os.path.join(user_data_dir(), "logs") if is_frozen() else "logs"


def resource_path(*parts: str) -> str:
    """Path to a bundled READ-ONLY asset (icon, etc.) - resolves inside
    the PyInstaller onefile temp extraction dir (sys._MEIPASS) when
    frozen, or the real project directory otherwise.

    Deliberately separate from user_data_dir(): that one is for
    WRITABLE runtime files (config/logs) that must live outside the
    temp extraction dir to actually persist - a frozen onefile exe
    re-extracts to a fresh temp dir every launch, so anything written
    there is gone the moment the process exits. Assets only ever need
    reading, so the temp extraction dir is exactly where they should
    come from when frozen."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.join(os.path.dirname(__file__), "..")
    return os.path.join(base, *parts)
