"""Ed25519 key generation, signing, and verification for the compute ledger."""

from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def generate_keypair() -> tuple[str, str]:
    """Generate an Ed25519 key pair.

    Returns:
        (private_key_b64, public_key_b64) — raw 32-byte keys, URL-safe base64.
    """
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return (
        base64.urlsafe_b64encode(private_bytes).decode("ascii"),
        base64.urlsafe_b64encode(public_bytes).decode("ascii"),
    )


def derive_keypair_from_seed(seed: str) -> tuple[str, str]:
    """Derive a stable Ed25519 key pair from a seed string (dev/default validator)."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    private_key = Ed25519PrivateKey.from_private_bytes(digest)
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return (
        base64.urlsafe_b64encode(private_bytes).decode("ascii"),
        base64.urlsafe_b64encode(public_bytes).decode("ascii"),
    )


def _load_private(private_key_b64: str) -> Ed25519PrivateKey:
    raw = base64.urlsafe_b64decode(private_key_b64.encode("ascii"))
    return Ed25519PrivateKey.from_private_bytes(raw)


def _load_public(public_key_b64: str) -> Ed25519PublicKey:
    raw = base64.urlsafe_b64decode(public_key_b64.encode("ascii"))
    return Ed25519PublicKey.from_public_bytes(raw)


def public_key_from_private(private_key_b64: str) -> str:
    """Derive the public key (b64) from a private key (b64)."""
    private_key = _load_private(private_key_b64)
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.urlsafe_b64encode(public_bytes).decode("ascii")


def sign_message(private_key_b64: str, message: bytes | str) -> str:
    """Sign a message; return URL-safe base64 signature."""
    if isinstance(message, str):
        message = message.encode("utf-8")
    signature = _load_private(private_key_b64).sign(message)
    return base64.urlsafe_b64encode(signature).decode("ascii")


def verify_signature(public_key_b64: str, message: bytes | str, signature_b64: str) -> bool:
    """Verify an Ed25519 signature. Returns False on any failure."""
    if isinstance(message, str):
        message = message.encode("utf-8")
    try:
        signature = base64.urlsafe_b64decode(signature_b64.encode("ascii"))
        _load_public(public_key_b64).verify(signature, message)
        return True
    except Exception:
        return False
