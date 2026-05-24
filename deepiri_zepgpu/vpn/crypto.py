"""Encryption utilities for storing sensitive WireGuard keys."""

from __future__ import annotations

import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from deepiri_zepgpu.vpn.config import vpn_settings


def get_encryption_key() -> bytes:
    key = vpn_settings.encryption_key.encode()
    if len(key) < 32:
        key = key.ljust(32, b"\0")
    return key[:32]


def encrypt_value(plaintext: str) -> str:
    key = get_encryption_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_value(encoded: str) -> str:
    key = get_encryption_key()
    data = base64.b64decode(encoded)
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()
