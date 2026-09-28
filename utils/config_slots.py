import os

from .channel_store import load_channel_states, save_channel_states

MAX_CONFIG_SLOTS = 20


def config_slots_dir(config_service) -> str:
    """Lives beside whatever config.json the app was given, same
    test-isolation scoping ConfigService/SensorLogWriter already use -
    a test writing to a temp work_dir never touches the real
    user_data_dir() and can't collide with another test's slots."""
    return os.path.join(os.path.dirname(config_service.path), "config_slots")


def slot_path(config_service, name: str) -> str:
    return os.path.join(config_slots_dir(config_service), f"{name}.ini")


def list_config_slots(config_service) -> list[str]:
    directory = config_slots_dir(config_service)
    if not os.path.isdir(directory):
        return []
    names = [f[:-4] for f in os.listdir(directory) if f.lower().endswith(".ini")]
    return sorted(names, key=str.lower)


def save_config_slot(config_service, name: str, states: dict) -> bool:
    """Writes `states` (AppController.channels.states - real
    ChannelState objects, same shape save_channel_states() already
    expects) to the named slot. Returns False without writing if this
    would create a slot beyond MAX_CONFIG_SLOTS - overwriting an
    existing slot is always allowed regardless of the cap."""
    existing = list_config_slots(config_service)
    if name not in existing and len(existing) >= MAX_CONFIG_SLOTS:
        return False
    os.makedirs(config_slots_dir(config_service), exist_ok=True)
    save_channel_states(states, slot_path(config_service, name))
    return True


def load_config_slot(config_service, name: str) -> dict:
    return load_channel_states(slot_path(config_service, name))


def delete_config_slot(config_service, name: str) -> bool:
    path = slot_path(config_service, name)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


def rename_config_slot(config_service, old_name: str, new_name: str) -> bool:
    """False on a no-op (missing source) or a collision with a
    DIFFERENT existing slot - never silently overwrites one, unlike
    save_config_slot()'s own explicit overwrite path."""
    if new_name == old_name:
        return True
    old_path = slot_path(config_service, old_name)
    new_path = slot_path(config_service, new_name)
    if not os.path.exists(old_path) or os.path.exists(new_path):
        return False
    os.rename(old_path, new_path)
    return True
