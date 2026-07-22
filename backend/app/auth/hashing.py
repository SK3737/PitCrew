"""
Password hashing using Argon2id (via argon2-cffi's low-level ``PasswordHasher``).

Deliberately not passlib/bcrypt: passlib is unmaintained and bcrypt silently
truncates passwords past 72 bytes. ``argon2.PasswordHasher`` defaults to the
Argon2id variant, which is the current OWASP-recommended choice.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password, returning an encoded Argon2id hash string."""
    return _hasher.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    """Return True if ``password`` matches ``hashed``, False otherwise (never raises)."""
    try:
        return _hasher.verify(hashed, password)
    except VerifyMismatchError:
        return False
