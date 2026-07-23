# ADR 0003: Hybrid RAG - dense + sparse fusion, cross-encoder rerank, inline citations

## Status

Accepted. Implemented in Phase 6.

## Context

The Knowledge specialist needs to answer maintenance questions with real, checkable citations rather than an LLM's unsupported claims, and the spec calls for "a production-style RAG pipeline with hybrid retrieval, reranking, and citations" as one of the project's headline signals.
Two retrieval failure modes needed covering, not just one: pure vector similarity under-weights exact terms (part numbers, model names), while pure full-text search misses paraphrases and synonyms a user's question is likely to use.
The corpus itself also had a constraint: no real manufacturer manual can be redistributed, so the knowledge base is a curated, synthetic set of markdown documents authored from publicly known service-interval norms per make/model.

## Decision

Fuse two independent rankings with Reciprocal Rank Fusion (RRF, `k=60`, the standard IR-literature default, left untuned per the brief) rather than picking a single retrieval signal:

- **Dense**: pgvector cosine similarity over a local CPU sentence-transformer embedding (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim, stored in a real `pgvector.sqlalchemy.Vector(384)` column).
- **Sparse**: Postgres full-text search (`GENERATED ALWAYS ... STORED` `tsvector` column, `ts_rank`), backed by a GIN index.

The fused candidate set (roughly the top 20) is then reranked by a local CPU cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) down to the final top 4-6 chunks that actually get sent to the LLM.
Each chunk carries `source`, `section`, and `chunk_id` metadata so the Knowledge agent's answer can cite `[n]` markers back to a real, resolvable passage, deduplicated by `chunk_id` into a `citations[]` list rather than dumping raw chunks into the prompt.
When retrieval is weak, the agent is instructed to refuse rather than invent an answer.

## Consequences

**Positive**:
Both retrieval failure modes are covered by construction, not by accident - a hand-built before/after fixture (Phase 6) demonstrates the reranker measurably improving the gold chunk's position versus raw RRF fusion alone, and a hybrid-search test independently confirms fusion is real fusion, not a dressed-up single signal.
Embeddings and reranking run entirely on CPU with no API call at inference time, which keeps RAG outside the project's no-paid-API and no-GPU constraints entirely, unlike the live chat-completion path.

**Negative, disclosed rather than silently accepted**:
The refusal threshold (the point at which the agent says "no documentation on this" instead of answering) was calibrated against a set of 15 probe questions, and the one test asserting the refusal behavior reuses one of those same 15 questions rather than an independently held-out one.
This proves the refusal mechanism executes against real retrieval and reranking, but it does not prove the threshold generalizes to questions outside its own calibration set - flagged in Phase 6's review as a candidate to revisit with a larger, independently-held-out eval set once evals-in-CI existed (Phase 9), and still open.
Citation replayability (used by the deterministic test/CI cassettes) depends on `KBChunk.chunk_id` being a plain autoincrement primary key that stays stable across runs, which only holds because the test suite recreates the schema fresh each run; this is a known fragility (Phase 7), safe in its failure mode (a shifted id causes a loud cassette miss, never a silently wrong citation), but not yet fixed by hashing chunk content instead of a DB id, since that would touch the shipped citation schema.
