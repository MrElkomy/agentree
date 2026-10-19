import base64

import pytest

from agentree.core.vault import (
    SealedSecret,
    Vault,
    VaultDecryptError,
    generate_master_key,
    parse_master_key,
)


def _vault(kid: str = "k1", **extra: bytes) -> Vault:
    return Vault(kid, {kid: parse_master_key(generate_master_key()), **extra})


def test_round_trip_and_no_plaintext_in_ciphertext() -> None:
    v = _vault()
    sealed = v.encrypt("sk-live-secret-value-1234", aad=b"owner-a")
    assert b"sk-live-secret" not in sealed.ciphertext + sealed.wrapped_dek
    assert v.decrypt(sealed, aad=b"owner-a") == "sk-live-secret-value-1234"


def test_same_plaintext_encrypts_differently() -> None:
    v = _vault()
    a, b = v.encrypt("same", aad=b"x"), v.encrypt("same", aad=b"x")
    assert a.ciphertext != b.ciphertext and a.wrapped_dek != b.wrapped_dek


def test_ciphertext_bound_to_owner() -> None:
    v = _vault()
    sealed = v.encrypt("secret", aad=b"business-a:cred-1")
    with pytest.raises(VaultDecryptError):
        v.decrypt(sealed, aad=b"business-b:cred-1")


@pytest.mark.parametrize("field", ["ciphertext", "wrapped_dek"])
def test_tampering_is_detected(field: str) -> None:
    v = _vault()
    sealed = v.encrypt("secret", aad=b"a")
    blob = bytearray(getattr(sealed, field))
    blob[-1] ^= 1
    tampered = SealedSecret(**{**sealed.__dict__, field: bytes(blob)})
    with pytest.raises(VaultDecryptError):
        v.decrypt(tampered, aad=b"a")


def test_wrong_master_key_cannot_decrypt() -> None:
    sealed = _vault().encrypt("secret", aad=b"a")
    with pytest.raises(VaultDecryptError):
        _vault().decrypt(sealed, aad=b"a")


def test_rotation_reads_old_key_and_flags_rewrap() -> None:
    old_key = parse_master_key(generate_master_key())
    old = Vault("k0", {"k0": old_key})
    sealed = old.encrypt("secret", aad=b"a")
    new = Vault("k1", {"k1": parse_master_key(generate_master_key()), "k0": old_key})
    assert new.decrypt(sealed, aad=b"a") == "secret"
    assert new.needs_rewrap(sealed)


@pytest.mark.parametrize("bad", ["not-base64!!", base64.b64encode(b"short").decode()])
def test_invalid_master_key_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_master_key(bad)
