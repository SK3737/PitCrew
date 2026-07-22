"""Unit tests for password hashing (Argon2id via argon2-cffi)."""

from app.auth.hashing import hash_password, verify_password


def test_hash_and_verify():
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password(hashed, "correct horse battery staple") is True
    assert verify_password(hashed, "wrong password") is False
