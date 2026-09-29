import os
import sys


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def user_data_dir() -> str:
    if is_frozen():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "Pseudo Random Noise Controller")
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


def resolve_app_icon_path() -> str | None:
    """Single source of truth for which file IS the app icon right now:
    branding_icon_path()'s user override if one has been saved, else the
    bundled default. Every place the icon appears - window, taskbar,
    title bar, and the header's Helix Defense mark - resolves it through
    here, so Change Logo/Reset updates all of them together instead of
    just the OS-level icon. Returns None only if even the bundled
    default is missing."""
    override = branding_icon_path()
    if os.path.exists(override):
        return override
    default = resource_path("assets", "icons", "app_icon.png")
    if os.path.exists(default):
        return default
    return None
