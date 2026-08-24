"""Auth API routes: register, login, token refresh, API key management.

POST /api/auth/register   — Create new user
POST /api/auth/login      — Login, get JWT token
POST /api/auth/refresh    — Refresh JWT token
POST /api/auth/api-keys   — Create API key
GET  /api/auth/me          — Get current user info
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from app.security.auth import AuthRepository, get_auth_repository, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    email: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str


class ApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, request: Request) -> TokenResponse | dict:
    """Register a new user and return JWT token."""
    repository = get_auth_repository(request)
    try:
        user = await repository.register_user(body.username, body.password, body.email)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=201)

    token = repository.create_jwt(user["user_id"], user["username"])
    return TokenResponse(
        access_token=token,
        user_id=user["user_id"],
        username=user["username"],
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse | dict:
    """Login and get JWT token."""
    repository = get_auth_repository(request)
    user = await repository.authenticate_user(body.username, body.password)
    if not user:
        return JSONResponse({"error": "Invalid credentials"})

    token = repository.create_jwt(
        user["user_id"], user["username"], is_admin=bool(user.get("is_admin"))
    )
    return TokenResponse(
        access_token=token,
        user_id=user["user_id"],
        username=user["username"],
    )


@router.post("/api-keys")
async def create_api_key(
    body: ApiKeyRequest,
    repository: AuthRepository = Depends(get_auth_repository),  # noqa: B008
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict:
    """Create a new API key (requires auth)."""
    key = await repository.register_api_key(body.name, user["user_id"])
    return {"api_key": key, "name": body.name}


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)) -> dict:  # noqa: B008
    """Get current user info."""
    return user
