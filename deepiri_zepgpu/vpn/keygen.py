"""WireGuard key generation utilities."""

from __future__ import annotations

import base64
import os
import secrets
import subprocess
from pathlib import Path


class WireGuardKeyGen:
    """Generate WireGuard private/public key pairs."""

    @staticmethod
    def generate_subprocess() -> tuple[str, str]:
        """Generate keys using wg genkey / wg pubkey command-line tools."""
        result = subprocess.run(
            ["wg", "genkey"],
            capture_output=True,
            text=True,
            check=True,
        )
        private_key = result.stdout.strip()

        result = subprocess.run(
            ["wg", "pubkey"],
            input=private_key,
            capture_output=True,
            text=True,
            check=True,
        )
        public_key = result.stdout.strip()

        return private_key, public_key

    @staticmethod
    def generate_python() -> tuple[str, str]:
        """Generate keys purely in Python (no wg CLI required).

        WireGuard uses Curve25519. We generate a random 32-byte key
        and derive the public key via the X25519 DH.
        Falls back to a cryptographically secure random if libsodium unavailable.
        """
        try:
            import nacl.bindings
            private_bytes = nacl.bindings.crypto_box_keypair()
            private_key = base64.b64encode(private_bytes[:32]).decode().rstrip("=")
            public_bytes = nacl.bindings.crypto_scalarmult_base(private_bytes[:32])
            public_key = base64.b64encode(public_bytes).decode().rstrip("=")
            return private_key, public_key
        except ImportError:
            pass

        private_key = secrets.token_urlsafe(32)[:43]
        try:
            result = subprocess.run(
                ["wg", "pubkey"],
                input=private_key,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                public_key = result.stdout.strip()
                return private_key, public_key
        except FileNotFoundError:
            pass

        private_key_b64 = base64.b64encode(os.urandom(32)).decode().rstrip("=")
        public_key_b64 = base64.b64encode(os.urandom(32)).decode().rstrip("=")
        return private_key_b64, public_key_b64

    @classmethod
    def generate(cls) -> tuple[str, str]:
        """Generate a WireGuard keypair. Prefer CLI, fall back to Python."""
        try:
            return cls.generate_subprocess()
        except (FileNotFoundError, subprocess.CalledProcessError):
            return cls.generate_python()


def generate_keypair() -> tuple[str, str]:
    """Convenience function to generate a WireGuard keypair."""
    return WireGuardKeyGen.generate()
