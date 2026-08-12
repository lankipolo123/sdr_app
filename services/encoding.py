"""Real AES-256-GCM encryption for whatever middleware/API layer ends
up sitting between this app and an external caller (e.g. a Malaysian
counterpart's own GUI) - NOT the RS422 wire protocol to the hardware,
which is fixed by the modules' own firmware and can never be changed
(see services/protocol/). This is for the layer above that: the
message a remote client sends before it ever gets translated into a
real hardware frame.

Currently wired into dev mode only, as a live demonstration that the
mechanism actually works - not yet connected to a real network
service, since the actual API/message vocabulary depends on
requirements (local vs. remote, read vs. write access) that haven't
been confirmed yet. The key generated here is a per-session demo key,
regenerated every app launch - real key distribution/rotation between
this app and an external party is a separate, unsolved problem for
whenever the real service gets built.
"""
import json
import os
import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE = 12  # AES-GCM's standard nonce size - must be unique per encryption, never reused with the same key


def generate_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encode_message(payload: dict, key: bytes) -> str:
    """dict -> JSON -> AES-256-GCM encrypt -> base64 text, ready to put
    on a wire. A fresh random nonce every call (prepended to the
    ciphertext, not secret - GCM's security comes from never reusing
    one with the same key, not from hiding it) means encoding the
    exact same payload twice produces a completely different string
    both times."""
    plaintext = json.dumps(payload).encode()
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ciphertext).decode()


def decode_message(encoded: str, key: bytes) -> dict:
    raw = base64.b64decode(encoded)
    nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return json.loads(plaintext)
