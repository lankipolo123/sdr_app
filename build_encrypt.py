import marshal
import os
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from crypto_loader import _KEY, _ARCHIVE_NAME

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(ROOT, _ARCHIVE_NAME)

# Our own app code only - never third-party packages (PySide6,
# cryptography itself), and never main.py/crypto_loader.py/build_*.py,
# which have to stay as plain, directly-importable bootstrap files for
# PyInstaller and the interpreter itself to find in the first place.
SOURCE_PACKAGES = ["app", "components", "hooks", "pages", "services", "state", "styles", "utils"]

# Standalone manual test/dev harnesses that live inside an otherwise-real
# package (services/) but are never imported by the shipped app itself -
# nothing in app.py's real import graph references them, so encrypting
# them would just bloat the archive with dead weight, not protect
# anything actually reachable at runtime.
EXCLUDE_FILES = {"test_transit_dll.py", "test_command_tokens.py", "team_vocab.py"}


def _iter_modules():
    for pkg in SOURCE_PACKAGES:
        top = os.path.join(ROOT, pkg)
        if os.path.isfile(top + ".py"):
            yield pkg, top + ".py", False
            continue
        for dirpath, _dirnames, filenames in os.walk(top):
            rel_dir = os.path.relpath(dirpath, ROOT)
            for name in filenames:
                if not name.endswith(".py") or name in EXCLUDE_FILES:
                    continue
                full_path = os.path.join(dirpath, name)
                if name == "__init__.py":
                    dotted = rel_dir.replace(os.sep, ".")
                    yield dotted, full_path, True
                else:
                    dotted = f"{rel_dir.replace(os.sep, '.')}.{name[:-3]}"
                    yield dotted, full_path, False


def _encrypt(source: str) -> bytes:
    code = compile(source, "<encrypted>", "exec")
    plaintext = marshal.dumps(code)
    nonce = os.urandom(12)
    ciphertext = AESGCM(_KEY).encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def main():
    count = 0
    with zipfile.ZipFile(OUT_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for dotted, path, is_package in _iter_modules():
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            entry = f"{dotted}/__init__.pyenc" if is_package else f"{dotted}.pyenc"
            zf.writestr(entry, _encrypt(source))
            count += 1
    print(f"encrypted {count} modules -> {OUT_PATH}")


if __name__ == "__main__":
    main()
