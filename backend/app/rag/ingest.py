"""
Structure-aware ingest for the Phase 6 RAG knowledge base.

Parses each `backend/data/kb/*.md` file's YAML front matter (`title`,
`source`, `make`, `model`) and markdown body, splits the body into one chunk
per `##` section (task 6.2's "structure-aware chunking" - a section is the
natural unit of a self-contained fact in these authored docs, unlike a fixed
token-count window that could split a fact from its own heading), embeds
each chunk via `app.agents.embeddings.embed_texts`, and upserts
`KBDocument`/`KBChunk` rows. `backend/scripts/ingest_kb.py` is the CLI
entrypoint; this module has no CLI/side-effecting concerns of its own so it
stays directly unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.embeddings import embed_texts
from app.models.kb import KBChunk, KBDocument

FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)", re.DOTALL)
SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


@dataclass
class ParsedChunk:
    section: str
    text: str


@dataclass
class ParsedDocument:
    path: str
    title: str
    source: str
    make: str | None
    vehicle_model: str | None
    chunks: list[ParsedChunk]


def parse_markdown_file(path: Path) -> ParsedDocument:
    """Parse one `data/kb/*.md` file into its front matter + section chunks."""
    raw = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(raw)
    if not match:
        raise ValueError(f"{path}: missing YAML front matter (expected a leading '---' block)")

    front_matter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)

    chunks = _chunk_by_section(body)
    if not chunks:
        raise ValueError(f"{path}: no '##' sections found to chunk")

    return ParsedDocument(
        path=str(path),
        title=front_matter.get("title", path.stem),
        source=front_matter.get("source", "unknown"),
        make=front_matter.get("make"),
        vehicle_model=front_matter.get("model"),
        chunks=chunks,
    )


def _chunk_by_section(body: str) -> list[ParsedChunk]:
    """Split a markdown body into one chunk per `##` section. Each chunk's
    text includes its own heading line, so the embedded/indexed text always
    carries the context of what section it came from rather than being a
    bare content-only fragment."""
    matches = list(SECTION_RE.finditer(body))
    chunks: list[ParsedChunk] = []
    for i, section_match in enumerate(matches):
        section = section_match.group(1).strip()
        start = section_match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_text = body[start:end].strip()
        if section_text:
            chunks.append(ParsedChunk(section=section, text=section_text))
    return chunks


async def ingest_document(session: AsyncSession, parsed: ParsedDocument) -> KBDocument:
    """Upsert one parsed document and its chunks.

    Idempotent by `path`: re-ingesting the same file deletes its previous
    chunk rows and re-inserts fresh ones (recomputing embeddings), so
    re-running `scripts/ingest_kb.py` after editing a corpus file never
    accumulates stale duplicate chunks.
    """
    existing = await session.scalar(select(KBDocument).where(KBDocument.path == parsed.path))
    if existing is not None:
        await session.execute(delete(KBChunk).where(KBChunk.document_id == existing.id))
        existing.title = parsed.title
        existing.source = parsed.source
        existing.make = parsed.make
        existing.vehicle_model = parsed.vehicle_model
        document = existing
    else:
        document = KBDocument(
            path=parsed.path,
            title=parsed.title,
            source=parsed.source,
            make=parsed.make,
            vehicle_model=parsed.vehicle_model,
        )
        session.add(document)
        await session.flush()  # assigns document.id for the chunks below

    texts = [chunk.text for chunk in parsed.chunks]
    vectors = embed_texts(texts)
    for index, (chunk, vector) in enumerate(zip(parsed.chunks, vectors)):
        session.add(
            KBChunk(
                document_id=document.id,
                chunk_index=index,
                section=chunk.section,
                text=chunk.text,
                embedding=vector,
            )
        )
    return document


async def ingest_kb_directory(session: AsyncSession, kb_dir: Path) -> int:
    """Ingest every `*.md` file directly under `kb_dir` and commit.

    Returns the total chunk count ingested across all documents, for the
    caller (`scripts/ingest_kb.py`) to report/verify.
    """
    total_chunks = 0
    for path in sorted(kb_dir.glob("*.md")):
        parsed = parse_markdown_file(path)
        await ingest_document(session, parsed)
        total_chunks += len(parsed.chunks)
    await session.commit()
    return total_chunks
