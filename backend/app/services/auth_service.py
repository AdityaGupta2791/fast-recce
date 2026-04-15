"""Auth primitives: password hashing + JWT issue/verify.

Framework-agnostic. The FastAPI layer wraps these in a `get_current_user`
dependency (see app/api/deps.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import bcrypt
from jose import ExpiredSignatureError, JWTError, jwt

from app.config import Settings

TokenType = Literal["access", "refresh"]


@dataclass(frozen=True)
class TokenClaims:
    user_id: UUID
    email: str
    role: str
    token_type: TokenType
    expires_at: datetime


def hash_password(plain: str) -> str:
    # bcrypt caps input at 72 bytes. Truncate explicitly so long passwords
    # don't raise — trade-off is that long passwords silently share a suffix.
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    user_id: UUID,
    email: str,
    role: str,
    settings: Settings,
) -> tuple[str, int]:
    expires_in = settings.access_token_expire_minutes * 60
    return (
        _encode(
            user_id=user_id,
            email=email,
            role=role,
            token_type="access",
            expires_delta=timedelta(seconds=expires_in),
            settings=settings,
        ),
        expires_in,
    )


def create_refresh_token(
    *,
    user_id: UUID,
    email: str,
    role: str,
    settings: Settings,
) -> str:
    return _encode(
        user_id=user_id,
        email=email,
        role=role,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
        settings=settings,
    )


def decode_token(token: str, *, settings: Settings) -> TokenClaims | None:
    """Return TokenClaims on valid token, None on invalid/expired."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except (ExpiredSignatureError, JWTError):
        return None

    try:
        return TokenClaims(
            user_id=UUID(str(payload["sub"])),
            email=str(payload.get("email", "")),
            role=str(payload.get("role", "viewer")),
            token_type=payload["type"],
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError):
        return None


# --- Internals ---


def _encode(
    *,
    user_id: UUID,
    email: str,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
    settings: Settings,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
