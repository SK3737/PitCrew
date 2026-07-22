"""FastAPI dependency that resolves the current user from a bearer access token."""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import decode_token
from app.db.session import get_session
from app.models.user import User
from app.repositories.users import UserRepository

# auto_error=False so a missing header raises our own 401 (HTTPBearer's
# default auto_error raises 403, which is the wrong status for "not
# authenticated" as opposed to "authenticated but not permitted").
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        claims = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    if claims.get("type") != "access":
        # Belt-and-braces: a refresh token (type "refresh") or any token
        # missing the claim entirely must never be trusted as an access
        # credential, even though it carries a valid signature and a real
        # user id in "sub". Mirrors the refresh-side check in
        # rotate_refresh_token that rejects an access token used as a
        # refresh token.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(int(claims["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user
