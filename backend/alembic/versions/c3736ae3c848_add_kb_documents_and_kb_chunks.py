"""add kb_documents and kb_chunks (RAG)

Revision ID: c3736ae3c848
Revises: 6bc9ea323f66
Create Date: 2026-07-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR


# revision identifiers, used by Alembic.
revision: str = 'c3736ae3c848'
down_revision: Union[str, Sequence[str], None] = '6bc9ea323f66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# sentence-transformers/all-MiniLM-L6-v2 output size - keep in lockstep with
# app.models.kb.EMBEDDING_DIM.
EMBEDDING_DIM = 384


def upgrade() -> None:
    """Upgrade schema."""
    # Phase 0 already ran this once against the dev DB (the pgvector/pgvector
    # image ships the extension binary, but it still has to be enabled per
    # database) - IF NOT EXISTS makes this idempotent there and ensures a
    # fresh CI/test database that only ever runs migrations gets it too.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "kb_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("make", sa.String(), nullable=True),
        sa.Column("vehicle_model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )
    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "content_tsv",
            TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["kb_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kb_chunks_document_id"), "kb_chunks", ["document_id"], unique=False)

    # No ivfflat/HNSW ANN index: an approximate index needs a `lists`/`probes`
    # tuning pass to get acceptable recall, and on a corpus this small (tens
    # of chunks, not millions) an ivfflat index with default probes=1
    # measurably *loses* real matches - confirmed while calibrating this
    # phase's rerank threshold, an ivfflat(lists=10) index silently dropped
    # `ORDER BY embedding <=> :v LIMIT 20` from 20 rows to 1. A plain exact
    # brute-force cosine scan is both correct and fast enough at this scale;
    # add an ANN index only once the corpus grows large enough to need one.
    op.execute("CREATE INDEX ix_kb_chunks_content_tsv ON kb_chunks USING gin (content_tsv)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_content_tsv")
    op.drop_index(op.f("ix_kb_chunks_document_id"), table_name="kb_chunks")
    op.drop_table("kb_chunks")
    op.drop_table("kb_documents")
