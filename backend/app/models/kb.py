"""
KB models for the Phase 6 RAG pipeline: ``kb_documents`` (one row per
authored markdown file under ``backend/data/kb/``) and ``kb_chunks`` (one
row per structure-aware chunk within a document - see ``app.rag.ingest``),
carrying both a pgvector embedding (for cosine-similarity search) and a
generated ``tsvector`` column (for Postgres full-text search) so
``app.rag.retrieval`` can fuse the two rankings via RRF.
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Integer, String
from sqlalchemy import Text as SqlText
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

# sentence-transformers/all-MiniLM-L6-v2 (see app.config.settings.EMBED_MODEL)
# outputs 384-dim vectors - this must stay in lockstep with that model.
EMBEDDING_DIM = 384


class KBDocument(Base):
    """One authored knowledge-base markdown file (see `data/kb/*.md`)."""

    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    make: Mapped[str | None] = mapped_column(String, nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chunks: Mapped[list["KBChunk"]] = relationship(
        "KBChunk", back_populates="document", cascade="all, delete-orphan"
    )


class KBChunk(Base):
    """One structure-aware chunk (a markdown ``##`` section) of a `KBDocument`.

    `content_tsv` is a Postgres `GENERATED ALWAYS AS ... STORED` column -
    SQLAlchemy never writes to it directly, Postgres derives it from `text`
    on every insert/update, which keeps the full-text index perfectly in
    sync with no application-level bookkeeping.
    """

    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(SqlText, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
        nullable=True,
    )

    document: Mapped["KBDocument"] = relationship("KBDocument", back_populates="chunks")
