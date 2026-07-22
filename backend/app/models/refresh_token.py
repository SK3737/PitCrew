from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RefreshToken(Base):
    """
    Server-side record of an issued refresh token, keyed by the JWT's ``jti``.

    The refresh JWT handed to the client is never stored verbatim - only its
    jti and validity metadata are, so rotation and reuse detection can be
    enforced without trusting client-held claims alone. ``replaced_by`` links
    a token to the jti that superseded it, forming a chain per login session;
    reuse of a ``revoked`` token means the chain has been compromised and the
    whole chain for that user is revoked.
    """

    __tablename__ = "refresh_tokens"

    jti: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replaced_by: Mapped[str | None] = mapped_column(String, nullable=True)
