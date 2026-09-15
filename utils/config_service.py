import copy
import json
import os

from .app_paths import user_data_dir, default_log_folder

DEFAULT_CONFIG = {
    "baud_rate": 115200,
    "parity": "N",
    "data_bits": 8,
    "log_folder": default_log_folder(),
    # Cumulative seconds the app has been running, across every session -
    # see AppController's uptime timer in hooks/use_app.py. 0 until the
    # first save.
    "total_uptime_seconds": 0,
    # sha256 hex digest of the Continuous Wave password, or absent until
    # one is set - see hooks/cw_auth.py. Never the plaintext password.
    "cw_password_hash": None,
}

CONFIG_PATH = os.path.join(user_data_dir(), "config", "config.json")


class ConfigService:

    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    loaded = json.load(f)
                self.data.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass
        return self.data

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
