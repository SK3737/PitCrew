"""
Auth routes: register, login, refresh (rotates), logout.

The refresh token is never returned in a JSON body - it only ever travels
as an HttpOnly, Secure, SameSite=strict cookie scoped to /auth, so client
JS can never read it and it is only ever sent back on auth endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_password, verify_password
from app.auth.tokens import (
    InvalidRefreshToken,
    RefreshTokenReused,
    create_access_token,
    decode_token,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.config import settings
from app.db.session import get_session
from app.repositories.users import UserRepository
from app.schemas.auth import AccessTokenResponse, LoginRequest, RegisterRequest, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"


def _refresh_cookie_max_age() -> int:
    return settings.REFRESH_TOKEN_DAYS * 24 * 60 * 60


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=_refresh_cookie_max_age(),
        path="/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/auth")


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_session)) -> UserPublic:
    user_repo = UserRepository(session)
    if await user_repo.get_by_email(payload.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = await user_repo.create(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    await session.commit()
    return UserPublic(id=user.id, email=user.email, role=user.role)


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> AccessTokenResponse:
    user_repo = UserRepository(session)
    user = await user_repo.get_by_email(payload.email)
    if user is None or not verify_password(user.hashed_password, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    access_token = create_access_token(user_id=user.id, role=user.role)
    refresh_token = await issue_refresh_token(session, user.id)
    await session.commit()

    _set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> AccessTokenResponse:
    old_refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if old_refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    try:
        new_refresh_token = await rotate_refresh_token(session, old_refresh_token)
    except RefreshTokenReused:
        # Persist the chain-wide revocation performed inside rotate_refresh_token
        # even though we're rejecting this request.
        await session.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token reuse detected")
    except InvalidRefreshToken:
        await session.rollback()
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    claims = decode_token(new_refresh_token)
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(int(claims["sub"]))
    if user is None:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token(user_id=user.id, role=user.role)
    await session.commit()

    _set_refresh_cookie(response, new_refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token is not None:
        await revoke_refresh_token(session, refresh_token)
        await session.commit()
    _clear_refresh_cookie(response)
