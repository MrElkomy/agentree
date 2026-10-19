"""Envelope encryption for customer secrets (BYOK provider keys).

Each secret gets its own random 256-bit data key (DEK). The secret is encrypted with the
DEK, and the DEK is encrypted ("wrapped") with the master key, both with AES-256-GCM from
the `cryptography` library. Associated data binds every ciphertext to its owner (business
and record id), so a ciphertext copied to another tenant or row fails to decrypt.

The master key never touches the database. It comes from the environment
(AGENTREE_MASTER_KEY, base64 of 32 bytes) and can later move to a KMS behind this module.
"""

import base64
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12


class VaultUnavailableError(RuntimeError):
    """No master key configured: secrets cannot be stored or read."""


class VaultDecryptError(RuntimeError):
    """Ciphertext is corrupted, tampered with, or bound to a different owner."""


@dataclass(frozen=True)
class SealedSecret:
    ciphertext: bytes
    wrapped_dek: bytes
    key_id: str


def parse_master_key(encoded: str) -> bytes:
    key = base64.b64decode(encoded, validate=True)
    if len(key) != 32:
        raise ValueError("master key must be 32 bytes (base64-encoded)")
    return key


class Vault:
    def __init__(self, active_key_id: str, keys: dict[str, bytes]) -> None:
        if active_key_id not in keys:
            raise ValueError("active master key id not among configured keys")
        self._active = active_key_id
        self._keys = keys

    @staticmethod
    def _seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)

    @staticmethod
    def _open(key: bytes, blob: bytes, aad: bytes) -> bytes:
        try:
            return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], aad)
        except InvalidTag:
            raise VaultDecryptError("secret cannot be decrypted for this owner") from None

    def encrypt(self, plaintext: str, *, aad: bytes) -> SealedSecret:
        dek = AESGCM.generate_key(bit_length=256)
        return SealedSecret(
            ciphertext=self._seal(dek, plaintext.encode(), aad),
            wrapped_dek=self._seal(self._keys[self._active], dek, aad),
            key_id=self._active,
        )

    def decrypt(self, sealed: SealedSecret, *, aad: bytes) -> str:
        master = self._keys.get(sealed.key_id)
        if master is None:
            raise VaultDecryptError("unknown master key id")
        dek = self._open(master, sealed.wrapped_dek, aad)
        return self._open(dek, sealed.ciphertext, aad).decode()

    def needs_rewrap(self, sealed: SealedSecret) -> bool:
        return sealed.key_id != self._active


def generate_master_key() -> str:
    """Generate a new master key (base64 of 32 random bytes) for AGENTREE_MASTER_KEY."""
    return base64.b64encode(os.urandom(32)).decode()
