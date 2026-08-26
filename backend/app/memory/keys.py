"""Validation and decoding for encrypted-memory master keys."""

from __future__ import annotations

import base64
import binascii
import re

_KEY_BYTES = 32
_URLSAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")
_WEAK_VALUES = {
    "changeme",
    "change-me",
    "change_me",
    "default",
    "placeholder",
    "<replace-with-at-least-32-byte-secret>",
}
_ERROR = "memory encryption master key must be a URL-safe base64 token encoding 32 bytes"


def decode_memory_master_key(value: str | bytes) -> bytes:
    """Return exactly 256 decoded key bits or raise a value-sanitized error."""
    if isinstance(value, bytes):
        if len(value) != _KEY_BYTES:
            raise ValueError(_ERROR)
        return value

    token = value.strip()
    lowered = token.casefold()
    if not token or lowered in _WEAK_VALUES:
        raise ValueError(_ERROR)
    if not _URLSAFE_TOKEN.fullmatch(token) or "=" in token[:-2]:
        raise ValueError(_ERROR)

    unpadded = token.rstrip("=")
    try:
        decoded = base64.b64decode(
            unpadded + "=" * (-len(unpadded) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError) as exc:
        raise ValueError(_ERROR) from exc
    if len(decoded) != _KEY_BYTES:
        raise ValueError(_ERROR)
    return decoded
