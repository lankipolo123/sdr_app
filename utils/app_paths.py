import os
import sys


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def user_data_dir() -> str:
    if is_frozen():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "SDR Controller")
    else:
        path = os.path.join(os.path.dirname(__file__), "..")
    os.makedirs(path, exist_ok=True)
    return path


def default_log_folder() -> str:
    return os.path.join(user_data_dir(), "logs") if is_frozen() else "logs"
