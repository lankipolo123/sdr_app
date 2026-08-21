import importlib.abc
import importlib.util
import marshal
import os
import sys
import zipfile

from Crypto.Cipher import AES

_KEY = bytes.fromhex(
    "55a04fcdf6615e5552689ef2d5ca135edca7299032377680f6fa23d5d84500c2"
)

_ARCHIVE_NAME = "app_encrypted.pyz"


def _archive_path() -> str:
    if getattr(sys, "frozen", False):
        # sys._MEIPASS is where PyInstaller actually places --add-data
        # files - the app's install folder itself (dirname of
        # sys.executable) only in --onefile mode; --onedir (what this
        # app builds) puts them in _internal/ instead. Confirmed by
        # building a real onedir test binary and checking - _MEIPASS is
        # set in both modes, just pointing at different real paths.
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, _ARCHIVE_NAME)


class _EncryptedLoader(importlib.abc.Loader):
    def __init__(self, zf: zipfile.ZipFile, entry: str, is_package: bool):
        self._zf = zf
        self._entry = entry
        self._is_package = is_package

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        blob = self._zf.read(self._entry)
        # Layout written by build_encrypt.py: nonce(12) + ciphertext + tag(16)
        # - pycryptodome keeps the GCM tag separate from the ciphertext
        # (unlike `cryptography`'s AESGCM, which returns them concatenated),
        # so it has to be split back off here.
        nonce, ciphertext, tag = blob[:12], blob[12:-16], blob[-16:]
        cipher = AES.new(_KEY, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        code = marshal.loads(plaintext)
        # Real modules always have __file__ - set a synthetic one so any
        # code touching it (even just for a log message or an early guard
        # clause a future edit might add) gets a real string instead of
        # a NameError, even though nothing in the real frozen build's
        # reachable branches dereferences it for an actual path today.
        module.__file__ = f"<encrypted:{self._entry}>"
        if self._is_package:
            module.__path__ = []
        exec(code, module.__dict__)

    def is_package(self, fullname):
        return self._is_package


class _EncryptedFinder(importlib.abc.MetaPathFinder):
    def __init__(self, archive_path: str):
        self._zf = zipfile.ZipFile(archive_path, "r")
        self._names = set(self._zf.namelist())

    def find_spec(self, fullname, path, target=None):
        pkg_entry = fullname + "/__init__.pyenc"
        mod_entry = fullname + ".pyenc"
        if pkg_entry in self._names:
            loader = _EncryptedLoader(self._zf, pkg_entry, is_package=True)
            return importlib.util.spec_from_loader(fullname, loader, is_package=True)
        if mod_entry in self._names:
            loader = _EncryptedLoader(self._zf, mod_entry, is_package=False)
            return importlib.util.spec_from_loader(fullname, loader, is_package=False)
        return None


def install() -> bool:
    # SDR_APP_FORCE_ENCRYPTED_LOADER lets build_encrypt.py's own test step
    # verify the encrypted archive actually loads correctly from plain
    # `python`, without needing a real frozen PyInstaller build to test
    # against - not read or relied on by the shipped app itself.
    if not getattr(sys, "frozen", False) and not os.environ.get("SDR_APP_FORCE_ENCRYPTED_LOADER"):
        return False
    path = _archive_path()
    if not os.path.exists(path):
        return False
    sys.meta_path.insert(0, _EncryptedFinder(path))
    return True
