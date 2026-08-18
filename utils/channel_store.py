import configparser
import os

from services.protocol import constants as c
from state.level_map import LEVEL_LABELS
from .app_paths import user_data_dir

CHANNEL_STORE_PATH = os.path.join(user_data_dir(), "config", "channels.ini")

_MODE_NAME_TO_CODE = {name: code for code, name in c.MODE_NAMES.items()}
_LEVEL_NAME_TO_LEVEL = {name: level for level, name in LEVEL_LABELS.items() if level > 0}


def load_channel_states(path: str = CHANNEL_STORE_PATH) -> dict[int, dict]:
    result: dict[int, dict] = {}
    if not os.path.exists(path):
        return result

    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error:
        return result

    for section in parser.sections():
        if not section.upper().startswith("CH"):
            continue
        try:
            address = int(section[2:]) - 1
        except ValueError:
            continue
        if address < 0:
            continue

        entry: dict = {}
        mode_name = parser.get(section, "mode", fallback=None)
        if mode_name in _MODE_NAME_TO_CODE:
            entry["mode"] = _MODE_NAME_TO_CODE[mode_name]

        power_name = parser.get(section, "power", fallback=None)
        if power_name in _LEVEL_NAME_TO_LEVEL:
            entry["last_level"] = _LEVEL_NAME_TO_LEVEL[power_name]

        output_str = parser.get(section, "output", fallback=None)
        if output_str in ("on", "off"):
            entry["output_on"] = output_str == "on"

        if entry:
            result[address] = entry
    return result


def save_channel_states(states: dict, path: str = CHANNEL_STORE_PATH):
    parser = configparser.ConfigParser()
    for address in sorted(states):
        state = states[address]
        d = state.data
        section = f"CH{state.display_number:02d}"
        parser[section] = {
            "mode": c.MODE_NAMES.get(d.mode, c.MODE_NAMES[c.BLIND_DEFAULT_MODE]),
            "power": LEVEL_LABELS[d.last_level],
            "output": "on" if d.output_on else "off",
        }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        parser.write(f)
