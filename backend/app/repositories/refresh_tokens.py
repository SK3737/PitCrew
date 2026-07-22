"""Data access for RefreshToken rows."""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        jti: str,
        user_id: int,
        expires_at: datetime,
    ) -> RefreshToken:
        token = RefreshToken(jti=jti, user_id=user_id, expires_at=expires_at)
        self.session.add(token)
        await self.session.flush()
        return token

    async def get(self, jti: str) -> RefreshToken | None:
        return await self.session.get(RefreshToken, jti)

    async def revoke(self, jti: str, replaced_by: str | None = None) -> None:
        token = await self.get(jti)
        if token is None:
            return
        token.revoked = True
        if replaced_by is not None:
            token.replaced_by = replaced_by
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: int) -> None:
        await self.session.execute(
            update(RefreshToken).where(RefreshToken.user_id == user_id).values(revoked=True)
        )
        await self.session.flush()
