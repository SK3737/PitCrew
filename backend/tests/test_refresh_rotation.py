"""Tests for refresh token rotation and reuse detection."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

from app.auth.tokens import (
    InvalidRefreshToken,
    RefreshTokenReused,
    decode_token,
    issue_refresh_token,
    rotate_refresh_token,
)
from app.config import settings
from app.models.user import User
from app.repositories.refresh_tokens import RefreshTokenRepository


async def _make_user(db_session) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", role="owner")
    db_session.add(user)
    await db_session.flush()
    return user


async def test_rotating_refresh_token_revokes_old_and_links_replaced_by(db_session):
    user = await _make_user(db_session)
    old_token = await issue_refresh_token(db_session, user.id)
    await db_session.commit()
    old_claims = decode_token(old_token)

    new_token = await rotate_refresh_token(db_session, old_token)
    await db_session.commit()
    new_claims = decode_token(new_token)

    repo = RefreshTokenRepository(db_session)
    old_row = await repo.get(old_claims["jti"])

    assert old_row.revoked is True
    assert old_row.replaced_by == new_claims["jti"]


async def test_reusing_a_rotated_refresh_token_revokes_whole_chain(db_session):
    user = await _make_user(db_session)
    token_a = await issue_refresh_token(db_session, user.id)
    await db_session.commit()

    token_b = await rotate_refresh_token(db_session, token_a)
    await db_session.commit()
    claims_b = decode_token(token_b)

    with pytest.raises(RefreshTokenReused):
        await rotate_refresh_token(db_session, token_a)
    await db_session.commit()

    repo = RefreshTokenRepository(db_session)
    row_b = await repo.get(claims_b["jti"])
    assert row_b.revoked is True  # entire chain revoked, including the not-yet-reused token


async def test_unknown_refresh_token_is_rejected(db_session):
    user = await _make_user(db_session)
    bogus_payload = {
        "sub": str(user.id),
        "jti": str(uuid.uuid4()),
        "type": "refresh",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }
    bogus_token = pyjwt.encode(bogus_payload, settings.JWT_SECRET, algorithm="HS256")

    with pytest.raises(InvalidRefreshToken):
        await rotate_refresh_token(db_session, bogus_token)
