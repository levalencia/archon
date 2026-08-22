"""Authentication: JWT tokens + API Key support.

JWT: for browser/UI users (login → token → bearer header)
API Key: for programmatic access (X-API-Key header)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = structlog.get_logger()

# Simple JWT implementation (no PyJWT dependency needed)
_JWT_SECRET = ""
_JWT_EXPIRY = 3600 * 24  # 24 hours
_API_KEYS: dict[str, dict] = {}  # key → {user_id, name}
_USERS: dict[str, dict] = {}  # user_id → {username, password_hash, email}

security = HTTPBearer(auto_error=False)


def configure_auth(secret: str, api_keys: dict | None = None) -> None:
    """Configure auth with secret and optional pre-registered API keys."""
    global _JWT_SECRET
    _JWT_SECRET = secret
    if api_keys:
        _API_KEYS.update(api_keys)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def register_user(username: str, password: str, email: str = "") -> dict:
    """Register a new user. Returns user dict."""
    user_id = str(uuid.uuid4())
    if any(u["username"] == username for u in _USERS.values()):
        msg = f"Username '{username}' already exists"
        raise ValueError(msg)

    _USERS[user_id] = {
        "user_id": user_id,
        "username": username,
        "password_hash": hash_password(password),
        "email": email,
    }
    logger.info("user_registered", user_id=user_id, username=username)
    return {"user_id": user_id, "username": username}


def authenticate_user(username: str, password: str) -> dict | None:
    """Verify credentials. Returns user dict or None."""
    pw_hash = hash_password(password)
    for user in _USERS.values():
        if user["username"] == username and user["password_hash"] == pw_hash:
            return user
    return None


def create_jwt(user_id: str, username: str) -> str:
    """Create a simple JWT token (HMAC-SHA256)."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "username": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + _JWT_EXPIRY,
    }

    import base64

    h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    msg = f"{h}.{p}"
    sig = hmac.new(_JWT_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}.{sig}"


def verify_jwt(token: str) -> dict | None:
    """Verify JWT token. Returns payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        msg = f"{parts[0]}.{parts[1]}"
        expected_sig = hmac.new(_JWT_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(parts[2], expected_sig):
            return None

        import base64

        payload_b = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b))

        if payload.get("exp", 0) < time.time():
            return None

        return payload
    except Exception:
        return None


def register_api_key(name: str, user_id: str = "system") -> str:
    """Create a new API key."""
    key = f"archon_{uuid.uuid4().hex}"
    _API_KEYS[key] = {"user_id": user_id, "name": name}
    logger.info("api_key_created", name=name)
    return key


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),  # noqa: B008
) -> dict:
    """Extract user from JWT bearer token or X-API-Key header.

    Returns: {user_id, username, auth_method}
    Raises 401 if no valid auth found.
    """
    # Check API Key first
    api_key = request.headers.get("X-API-Key", "")
    if api_key and api_key in _API_KEYS:
        key_info = _API_KEYS[api_key]
        return {
            "user_id": key_info["user_id"],
            "username": key_info.get("name", "api"),
            "auth_method": "api_key",
        }

    # Check JWT Bearer token
    if credentials and credentials.credentials:
        payload = verify_jwt(credentials.credentials)
        if payload:
            return {
                "user_id": payload["sub"],
                "username": payload.get("username", ""),
                "auth_method": "jwt",
            }

    raise HTTPException(status_code=401, detail="Not authenticated")


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),  # noqa: B008
) -> dict | None:
    """Like get_current_user but returns None instead of 401.

    Use for endpoints that work with or without auth.
    """
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None
