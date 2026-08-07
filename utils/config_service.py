import copy
import json
import os

from .app_paths import user_data_dir, default_log_folder

DEFAULT_CONFIG = {
    "baud_rate": 115200,
    "parity": "N",
    "data_bits": 8,
    "log_folder": default_log_folder(),
}

CONFIG_PATH = os.path.join(user_data_dir(), "config", "config.json")


class ConfigService:
    """Plain overwrite-on-save JSON - small, infrequent writes, no accounts
    file and no action log (both removed from scope along with roles)."""

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
                pass  # fall back to defaults silently; don't crash on a bad config file
        return self.data

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
