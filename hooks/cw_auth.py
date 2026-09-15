import hashlib


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class CwAuth:
    """Gates Continuous Wave (CW) mode behind a password - see
    ChannelCard._on_mode_set(), the only place this is checked. One
    instance is shared by every channel card (AppController owns it), so
    unlocking once covers the whole session instead of prompting per
    channel/per click.

    The password itself is never stored - only its sha256 hash, under
    config.json's 'cw_password_hash'. With no hash stored yet, the first
    attempt to arm CW bootstraps one (see PasswordDialog.set_new()).
    """

    CONFIG_KEY = "cw_password_hash"

    def __init__(self, config_service):
        self.config = config_service
        self.authorized = False

    def is_set(self) -> bool:
        return bool(self.config.get(self.CONFIG_KEY))

    def set_password(self, password: str):
        self.config.set(self.CONFIG_KEY, _hash_password(password))
        self.config.save()
        self.authorized = True

    def verify(self, password: str) -> bool:
        stored = self.config.get(self.CONFIG_KEY)
        ok = bool(stored) and _hash_password(password) == stored
        if ok:
            self.authorized = True
        return ok
