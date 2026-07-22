"""JWT access token creation/decoding (PyJWT, HS256)."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

ALGORITHM = "HS256"


def create_access_token(user_id: int, role: str) -> str:
    """Encode a short-lived access token carrying the user id, role, and a jti."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT, returning its claims. Raises on bad signature/expiry."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
