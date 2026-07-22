"""Unit tests for JWT access token creation/decoding."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.auth.tokens import create_access_token, decode_token
from app.config import settings


def test_access_token_roundtrip():
    token = create_access_token(user_id=1, role="admin")

    claims = decode_token(token)

    assert claims["sub"] == "1"
    assert claims["role"] == "admin"
    assert "jti" in claims
    assert "exp" in claims


def test_expired_access_token_raises():
    expired_payload = {
        "sub": "1",
        "role": "admin",
        "jti": "some-jti",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    expired_token = jwt.encode(expired_payload, settings.JWT_SECRET, algorithm="HS256")

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(expired_token)
