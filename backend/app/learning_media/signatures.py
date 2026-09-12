"""Short-lived HMAC tokens for browser-native media playback."""

from __future__ import annotations

import base64
import hmac
import json
import time
from typing import TypedDict

_DOMAIN = b"cogentrex/learning-media/v1"


class MediaToken(TypedDict):
    artifact_id: str
    checksum: str
    expires_at: int


def _key(secret: str) -> bytes:
    return hmac.digest(secret.encode("utf-8"), _DOMAIN, "sha256")


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_media_token(secret: str, *, artifact_id: str, checksum: str, expires_at: int) -> str:
    """Sign immutable artifact identity and expiry; never sign a filesystem path."""
    payload = json.dumps(
        {"artifact_id": artifact_id, "checksum": checksum, "expires_at": expires_at},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _encode(payload)
    signature = _encode(hmac.digest(_key(secret), encoded.encode("ascii"), "sha256"))
    return f"{encoded}.{signature}"


def verify_media_token(secret: str, token: str, *, now: int | None = None) -> MediaToken | None:
    """Return validated token data, or None for malformed, tampered, or expired tokens."""
    try:
        encoded, supplied = token.split(".", 1)
        expected = _encode(hmac.digest(_key(secret), encoded.encode("ascii"), "sha256"))
        if not hmac.compare_digest(expected, supplied):
            return None
        raw = json.loads(_decode(encoded))
        parsed: MediaToken = {
            "artifact_id": str(raw["artifact_id"]),
            "checksum": str(raw["checksum"]),
            "expires_at": int(raw["expires_at"]),
        }
        current = int(time.time()) if now is None else now
        if parsed["expires_at"] <= current:
            return None
        if len(parsed["checksum"]) != 64 or not parsed["artifact_id"]:
            return None
        return parsed
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
