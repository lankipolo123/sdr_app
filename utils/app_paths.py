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
    if is_frozen():
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.join(os.path.dirname(__file__), "..")
    return os.path.join(base, *parts)


def branding_icon_path() -> str:
    """User-swappable override, same convention as the C rewrite's
    branding/icon.ico: a branding/icon.png dropped next to the
    installed app (or set live via the in-app Change Logo action)
    overrides the app/window/taskbar icon. The --onedir install
    directory (see installer.iss's PrivilegesRequired=lowest per-user
    install) is writable without elevation, so this works the same way
    post-install as it does in dev."""
    if is_frozen():
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.join(os.path.dirname(__file__), "..")
    return os.path.join(base, "branding", "icon.png")
