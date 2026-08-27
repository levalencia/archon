"""Validation and decoding for encrypted-memory master keys."""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

_KEY_BYTES = 32
_CANONICAL_TOKEN_LENGTH = 43
_URLSAFE_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_WEAK_VALUES = {
    "changeme",
    "change-me",
    "change_me",
    "default",
    "placeholder",
    "<replace-with-at-least-32-byte-secret>",
}
_ERROR = (
    "memory encryption master key must be a canonical unpadded URL-safe base64 token "
    "encoding 32 bytes"
)


def decode_memory_master_key(value: str | bytes) -> bytes:
    """Return exactly 256 decoded key bits or raise a value-sanitized error."""
    if isinstance(value, bytes):
        if len(value) != _KEY_BYTES:
            raise ValueError(_ERROR)
        return value

    if (
        len(value) != _CANONICAL_TOKEN_LENGTH
        or value.casefold() in _WEAK_VALUES
        or _URLSAFE_TOKEN.fullmatch(value) is None
    ):
        raise ValueError(_ERROR)

    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(_ERROR) from exc

    canonical = base64.urlsafe_b64encode(decoded).decode().rstrip("=")
    if len(decoded) != _KEY_BYTES or canonical != value:
        raise ValueError(_ERROR)
    return decoded


_KEYRING_ERROR = "memory encryption keyring configuration is invalid"


@dataclass(frozen=True, slots=True)
class MemoryKeyring:
    active_version: int
    keys: Mapping[int, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.active_version) is not int or not 1 <= self.active_version <= 255:
            raise ValueError(_KEYRING_ERROR)
        normalized: dict[int, bytes] = {}
        for version, key in self.keys.items():
            if type(version) is not int or not 1 <= version <= 255:
                raise ValueError(_KEYRING_ERROR)
            normalized[version] = decode_memory_master_key(key)
        if self.active_version not in normalized or len(set(normalized.values())) != len(normalized):
            raise ValueError(_KEYRING_ERROR)
        object.__setattr__(self, "keys", MappingProxyType(normalized))

    def key(self, version: int) -> bytes:
        try:
            return self.keys[version]
        except (KeyError, TypeError):
            raise ValueError("memory encryption key version is unavailable") from None


def load_memory_keyring(
    serialized: str,
    *,
    active_version: int,
    legacy_master_key: str | bytes,
) -> MemoryKeyring:
    """Decode a versioned keyring or the legacy version-1 configuration."""

    if not serialized:
        if active_version != 1:
            raise ValueError(_KEYRING_ERROR)
        return MemoryKeyring(1, {1: decode_memory_master_key(legacy_master_key)})
    try:
        raw = json.loads(serialized)
    except (json.JSONDecodeError, TypeError):
        raise ValueError(_KEYRING_ERROR) from None
    if not isinstance(raw, dict) or not raw:
        raise ValueError(_KEYRING_ERROR)
    keys: dict[int, bytes] = {}
    for raw_version, token in raw.items():
        if (
            not isinstance(raw_version, str)
            or not raw_version.isascii()
            or not raw_version.isdecimal()
            or str(int(raw_version)) != raw_version
            or not isinstance(token, str)
        ):
            raise ValueError(_KEYRING_ERROR)
        version = int(raw_version)
        try:
            keys[version] = decode_memory_master_key(token)
        except ValueError:
            raise ValueError(_KEYRING_ERROR) from None
    return MemoryKeyring(active_version, keys)
