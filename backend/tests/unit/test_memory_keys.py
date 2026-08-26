"""Unit tests for canonical encrypted-memory master-key parsing."""

from __future__ import annotations

import base64
import secrets

import pytest

from app.memory.keys import decode_memory_master_key

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
