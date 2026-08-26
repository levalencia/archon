"""Validation and decoding for encrypted-memory master keys."""

from __future__ import annotations

import base64
import binascii
import re

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
