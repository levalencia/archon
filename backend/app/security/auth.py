"""Persistent authentication with scrypt passwords, JWTs, and API keys."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.db_store import DatabaseStore

security = HTTPBearer(auto_error=False)
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY = timedelta(hours=24)


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash a password with scrypt and a unique random salt."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    salt_text = base64.urlsafe_b64encode(salt).decode()
    digest_text = base64.urlsafe_b64encode(digest).decode()
    return f"scrypt${salt_text}${digest_text}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_text, digest_text = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(digest_text)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


class AuthRepository:
    """Persistent user and API-key operations backed by the application database."""

    def __init__(self, store: DatabaseStore, secret: str, admin_usernames: list[str] | None = None):
        self.store = store
        self.secret = secret
        self.admin_usernames = set(admin_usernames or [])

    async def register_user(self, username: str, password: str, email: str = "") -> dict:
        return await self.store.create_user(
            username,
            hash_password(password),
            email,
            is_admin=username in self.admin_usernames,
        )

    async def authenticate_user(self, username: str, password: str) -> dict | None:
        user = await self.store.get_user_by_username(username)
        return user if user and verify_password(password, user["password_hash"]) else None

    async def register_api_key(self, name: str, user_id: str) -> str:
        key = f"archon_{secrets.token_hex(24)}"
        await self.store.create_api_key(
            str(uuid.uuid4()), hashlib.sha256(key.encode()).hexdigest(), user_id, name
        )
        return key

    async def resolve_api_key(self, key: str) -> dict | None:
        key_info = await self.store.find_api_key_by_hash(hashlib.sha256(key.encode()).hexdigest())
        if key_info is None:
            return None
        user = await self.store.get_user(key_info["user_id"])
        if user is None:
            return None
        return {
            "user_id": user["user_id"],
            "username": user["username"],
            "name": key_info["name"],
            "is_admin": user["is_admin"],
        }

    @staticmethod
    def _base64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode_base64url(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def create_jwt(
        self,
        user_id: str,
        username: str,
        *,
        is_admin: bool = False,
        expires_delta: timedelta | None = None,
    ) -> str:
        """Create a standards-compliant HS256 JWT using only the standard library."""
        issued_at = int(time.time())
        expiry = issued_at + int((expires_delta or _JWT_EXPIRY).total_seconds())
        header = self._base64url(
            json.dumps({"alg": _JWT_ALGORITHM, "typ": "JWT"}, separators=(",", ":")).encode()
        )
        payload = self._base64url(
            json.dumps(
                {
                    "sub": user_id,
                    "username": username,
                    "is_admin": is_admin,
                    "iat": issued_at,
                    "exp": expiry,
                },
                separators=(",", ":"),
            ).encode()
        )
        signing_input = f"{header}.{payload}".encode("ascii")
        signature = self._base64url(hmac.digest(self.secret.encode(), signing_input, "sha256"))
        return f"{header}.{payload}.{signature}"

    def verify_jwt(self, token: str) -> dict | None:
        """Verify signature, algorithm, subject, and expiry of an HS256 JWT."""
        try:
            header_part, payload_part, supplied_signature = token.split(".")
            header = json.loads(self._decode_base64url(header_part))
            if header != {"alg": _JWT_ALGORITHM, "typ": "JWT"}:
                return None
            signing_input = f"{header_part}.{payload_part}".encode("ascii")
            expected_signature = self._base64url(
                hmac.digest(self.secret.encode(), signing_input, "sha256")
            )
            if not hmac.compare_digest(expected_signature, supplied_signature):
                return None
            payload = json.loads(self._decode_base64url(payload_part))
            if not payload.get("sub") or int(payload.get("exp", 0)) <= int(time.time()):
                return None
            return payload
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None


def get_auth_repository(request: Request) -> AuthRepository:
    return request.app.state.auth


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),  # noqa: B008
) -> dict:
    repository = get_auth_repository(request)
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        user = await repository.resolve_api_key(api_key)
        if user:
            return {**user, "auth_method": "api_key"}

    token = credentials.credentials if credentials else request.cookies.get("archon_token", "")
    if token:
        payload = repository.verify_jwt(token)
        if payload:
            user = await repository.store.get_user(payload["sub"])
            if user:
                return {
                    "user_id": user["user_id"],
                    "username": user["username"],
                    "auth_method": "jwt",
                    "is_admin": user["is_admin"],
                }
    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:  # noqa: B008
    if user.get("is_admin") is True:
        return user
    raise HTTPException(status_code=403, detail="Administrator access required")


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),  # noqa: B008
) -> dict | None:
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None
