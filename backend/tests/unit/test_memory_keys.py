"""Unit tests for canonical encrypted-memory master-key parsing."""

from __future__ import annotations

import base64
import secrets

import pytest

from app.memory.keys import MemoryKeyring, decode_memory_master_key, load_memory_keyring

_RAW_KEY = b"1" * 32
_CANONICAL_KEY = base64.urlsafe_b64encode(_RAW_KEY).decode().rstrip("=")


def test_generated_master_keys_round_trip() -> None:
    for _ in range(20):
        token = secrets.token_urlsafe(32)

        assert len(token) == 43
        assert decode_memory_master_key(token) == base64.urlsafe_b64decode(token + "=")


def test_exactly_32_raw_key_bytes_remain_supported() -> None:
    assert decode_memory_master_key(_RAW_KEY) == _RAW_KEY


@pytest.mark.parametrize(
    "invalid_key",
    [
        "",
        "changeme",
        "CHANGE-ME",
        "default",
        "placeholder",
        "<replace-with-at-least-32-byte-secret>",
        base64.urlsafe_b64encode(b"x" * 31).decode().rstrip("="),
        base64.urlsafe_b64encode(b"x" * 33).decode().rstrip("="),
        f" {_CANONICAL_KEY}",
        f"{_CANONICAL_KEY} ",
        f"\t{_CANONICAL_KEY}",
        f"{_CANONICAL_KEY}\n",
        f"{_CANONICAL_KEY[:20]} {_CANONICAL_KEY[20:]}",
        f"{_CANONICAL_KEY}=",
        f"{_CANONICAL_KEY}==",
        base64.b64encode(bytes([251]) * 32).decode().rstrip("="),
        f"{_CANONICAL_KEY[:-1]}!",
        f"{_CANONICAL_KEY[:-1]}F",  # Non-zero discarded bits: decodes as an alias.
    ],
)
def test_rejects_noncanonical_master_key_strings(invalid_key: str) -> None:
    with pytest.raises(ValueError, match="^memory encryption master key") as caught:
        decode_memory_master_key(invalid_key)

    if invalid_key:
        assert invalid_key not in str(caught.value)


@pytest.mark.parametrize("invalid_key", [b"", b"x" * 31, b"x" * 33])
def test_rejects_raw_keys_that_are_not_exactly_32_bytes(invalid_key: bytes) -> None:
    with pytest.raises(ValueError, match="^memory encryption master key"):
        decode_memory_master_key(invalid_key)


def test_legacy_key_loads_as_active_version_one() -> None:
    keyring = load_memory_keyring("", active_version=1, legacy_master_key=_CANONICAL_KEY)
    assert keyring.active_version == 1
    assert keyring.key(1) == _RAW_KEY


def test_versioned_keyring_uses_active_and_previous_versions_without_repr_leak() -> None:
    second_raw = b"2" * 32
    second = base64.urlsafe_b64encode(second_raw).decode().rstrip("=")
    serialized = f'{{"1":"{_CANONICAL_KEY}","2":"{second}"}}'
    keyring = load_memory_keyring(serialized, active_version=2, legacy_master_key="")

    assert keyring.active_version == 2
    assert keyring.key(1) == _RAW_KEY
    assert keyring.key(2) == second_raw
    assert _CANONICAL_KEY not in repr(keyring)
    assert second not in repr(keyring)


@pytest.mark.parametrize(
    "serialized,active",
    [
        ("{}", 1),
        ('{"1":"not-a-key"}', 1),
        (f'{{"1":"{_CANONICAL_KEY}"}}', 2),
        (f'{{"01":"{_CANONICAL_KEY}"}}', 1),
    ],
)
def test_invalid_keyring_configuration_is_sanitized(serialized: str, active: int) -> None:
    with pytest.raises(ValueError, match="^memory encryption keyring configuration is invalid$"):
        load_memory_keyring(serialized, active_version=active, legacy_master_key="")
    assert serialized not in "memory encryption keyring configuration is invalid"


def test_keyring_rejects_reused_key_material_and_unknown_version() -> None:
    with pytest.raises(ValueError, match="keyring configuration"):
        MemoryKeyring(2, {1: _RAW_KEY, 2: _RAW_KEY})
    keyring = MemoryKeyring(1, {1: _RAW_KEY})
    with pytest.raises(ValueError, match="version is unavailable"):
        keyring.key(2)
