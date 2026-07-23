"""
Ingest the knowledge-base corpus (`backend/data/kb/*.md`) into Postgres:
chunk, embed, and upsert `kb_documents`/`kb_chunks` rows.

Usage (from backend/):
    python -m scripts.ingest_kb
    python -m scripts.ingest_kb --kb-dir path/to/other/kb

Safe to re-run: `app.rag.ingest.ingest_document` is idempotent per file path
(re-ingesting a file replaces its chunks rather than duplicating them), so
editing a corpus file and re-running this script is the normal workflow.
"""

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import func, select

from app.db.session import async_session_factory
from app.models.kb import KBChunk, KBDocument
from app.rag.ingest import ingest_kb_directory

DEFAULT_KB_DIR = Path(__file__).resolve().parents[1] / "data" / "kb"


async def run(kb_dir: Path = DEFAULT_KB_DIR) -> tuple[int, int]:
    """Ingest every `*.md` file under `kb_dir`. Returns (document_count, chunk_count)."""
    async with async_session_factory() as session:
        await ingest_kb_directory(session, kb_dir)
        document_count = await session.scalar(select(func.count()).select_from(KBDocument))
        chunk_count = await session.scalar(select(func.count()).select_from(KBChunk))
    return document_count or 0, chunk_count or 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-dir", type=Path, default=DEFAULT_KB_DIR)
    args = parser.parse_args()

    document_count, chunk_count = asyncio.run(run(args.kb_dir))
    print(f"Ingested knowledge base: {document_count} document(s), {chunk_count} chunk(s) total.")


if __name__ == "__main__":
    main()
