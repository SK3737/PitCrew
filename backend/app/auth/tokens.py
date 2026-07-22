"""
JWT access + refresh token handling (PyJWT, HS256).

Access tokens are stateless (any validly-signed, unexpired token is trusted).
Refresh tokens are additionally tracked server-side (see
``app.repositories.refresh_tokens.RefreshTokenRepository``) so they can be
rotated on use and revoked - a bare JWT has no way to be invalidated before
its expiry otherwise.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.refresh_tokens import RefreshTokenRepository

ALGORITHM = "HS256"


class InvalidRefreshToken(Exception):
    """Raised when a refresh token is malformed, expired, or unknown to the server."""


class RefreshTokenReused(Exception):
    """
    Raised when a refresh token that was already rotated (or revoked) is
    presented again. This signals possible token theft, so the entire
    refresh chain for that user is revoked as a precaution.
    """


def create_access_token(user_id: int, role: str) -> str:
    """Encode a short-lived access token carrying the user id, role, and a jti."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": str(uuid.uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT, returning its claims. Raises on bad signature/expiry."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])


def _encode_refresh_jwt(user_id: int, jti: str, issued_at: datetime, expires_at: datetime) -> str:
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


async def issue_refresh_token(session: AsyncSession, user_id: int) -> str:
    """Create a brand-new refresh token (new login session) for ``user_id``."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_DAYS)
    jti = str(uuid.uuid4())

    repo = RefreshTokenRepository(session)
    await repo.create(jti=jti, user_id=user_id, expires_at=expires_at)

    return _encode_refresh_jwt(user_id, jti, now, expires_at)


async def rotate_refresh_token(session: AsyncSession, refresh_jwt: str) -> str:
    """
    Exchange a valid, not-yet-used refresh token for a new one.

    Rotation revokes the presented token and links it to its replacement.
    Presenting a token that has already been rotated away (or revoked) is
    treated as reuse: the whole chain for that user is revoked and
    ``RefreshTokenReused`` is raised, forcing a fresh login.
    """
    try:
        claims = decode_token(refresh_jwt)
    except jwt.PyJWTError as exc:
        raise InvalidRefreshToken(str(exc)) from exc

    if claims.get("type") != "refresh":
        # Belt-and-braces: an access token would also fail the jti lookup
        # below (its jti was never written to refresh_tokens), but checking
        # the claim explicitly makes the rejection reason unambiguous rather
        # than relying on that as an accident of the schema.
        raise InvalidRefreshToken("not a refresh token")

    jti = claims.get("jti")
    user_id = int(claims["sub"])

    repo = RefreshTokenRepository(session)
    row = await repo.get(jti)

    if row is None:
        raise InvalidRefreshToken("unknown refresh token")

    if row.revoked:
        await repo.revoke_all_for_user(user_id)
        raise RefreshTokenReused("refresh token reuse detected; all sessions revoked")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_DAYS)
    new_jti = str(uuid.uuid4())

    await repo.create(jti=new_jti, user_id=user_id, expires_at=expires_at)
    await repo.revoke(jti, replaced_by=new_jti)

    return _encode_refresh_jwt(user_id, new_jti, now, expires_at)


async def revoke_refresh_token(session: AsyncSession, refresh_jwt: str) -> None:
    """Revoke a refresh token (logout). Silently no-ops on an already-invalid token."""
    try:
        claims = decode_token(refresh_jwt)
    except jwt.PyJWTError:
        return

    repo = RefreshTokenRepository(session)
    await repo.revoke(claims["jti"])
