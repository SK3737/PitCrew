"""
Populate/refresh the committed CI cassettes from a live Groq pass.

This is the human-run counterpart to ``app.agents.llm_client.GroqClient``'s
record mode (task 7.1): it drives a fixed set of named scenarios through the
real production code paths (``app.agents.supervisor.ask`` /
``app.agents.specialists.knowledge.run_knowledge``) using a ``GroqClient``
built with ``record_dir`` set, so every request this app can actually make
gets written to a cassette keyed by ``app.agents.llm_client.request_hash`` -
the exact same key ``ReplayClient`` looks up. No hand-computed hashes, no
translation step: run this once against live Groq and the cassettes it
writes are immediately replayable offline.

Requires (neither of which this repo's test suite or CI ever needs):

- ``GROQ_API_KEY`` set to a real key - this script always talks to Groq
  directly via a record-mode ``GroqClient``, never through
  ``build_default_client()``/``settings.LLM_BACKEND`` (recording must always
  hit the live provider, independent of whatever backend the rest of the app
  is configured for).
- A reachable Postgres database (``DATABASE_URL``) for the knowledge
  scenario's real RAG pipeline - this script ingests the checked-in
  ``backend/data/kb/*.md`` corpus itself (idempotently, see
  ``app.rag.ingest.ingest_kb_directory``) before running it. No database
  content is needed for the diagnostics scenario: it drives a fixed,
  hand-specified vehicle snapshot (see ``_FixedVehicleSnapshot`` below)
  rather than a live ``RepositoryVehicleDataProvider``, deliberately -
  golden cassettes are meant to be a stable long-lived reference (frontend
  e2e and eval fixtures pin against them by name), and
  `RepositoryVehicleDataProvider` computes `months_driven`/`kms_driven`
  relative to ``date.today()``, which would make every field of a
  DB-backed recording drift by the day it happened to be recorded on.

Usage (from backend/):
    GROQ_API_KEY=... python -m scripts.record_cassettes
    GROQ_API_KEY=... python -m scripts.record_cassettes --out cassettes/golden

Note on reproducibility: pinning temperature=0.0/seed=0 (record mode always
does, see ``GroqClient``) is *best-effort* determinism - Groq's API does not
guarantee bit-identical completions across calls even so. Re-running this
script against a live key may therefore produce cassettes with the same
tool-calls/routing but slightly different prose than the currently-committed
``backend/cassettes/golden/*.json`` - those were hand-synthesized (this
project has no live Groq key available in CI or dev), not recorded; see
``task-7-report.md`` for exactly how and why. Re-review
``backend/tests/test_replay_mode.py``'s assertions after a real recording
pass in case wording-sensitive assertions need loosening.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from app.agents.llm_client import GroqClient
from app.agents.supervisor import ask
from app.agents.tools import AgentDeps, RepositoryKBSearchProvider, VehicleServiceSnapshot
from app.db.session import async_session_factory
from app.rag.ingest import ingest_kb_directory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
KB_DIR = BACKEND_ROOT / "data" / "kb"
DEFAULT_OUT_DIR = BACKEND_ROOT / "cassettes" / "golden"

# Fixed, hand-specified snapshot for the diagnostics golden scenario - see
# the module docstring for why this isn't RepositoryVehicleDataProvider.
GOLDEN_VEHICLE_ID = "V001"
GOLDEN_VEHICLE_SNAPSHOT = VehicleServiceSnapshot(
    vehicle_id=GOLDEN_VEHICLE_ID,
    months_driven=5.0,
    kms_driven=6000.0,
    make="Toyota",
    vehicle_model="Corolla",
    year=2020,
    fuel_type="petrol",
    last_service_type="oil_change",
)

GOLDEN_DIAGNOSTICS_QUESTION = f"When does {GOLDEN_VEHICLE_ID} need its next service?"
GOLDEN_KNOWLEDGE_QUESTION = "How often should I flush the coolant on a BMW 3 Series?"


class _FixedVehicleData:
    """VehicleDataProvider returning one hand-specified, date-independent
    snapshot - keeps the diagnostics golden cassette stable forever."""

    async def get_snapshot(self, vehicle_id: str) -> Optional[VehicleServiceSnapshot]:
        return GOLDEN_VEHICLE_SNAPSHOT if vehicle_id == GOLDEN_VEHICLE_ID else None


async def record(out_dir: Path) -> None:
    client = GroqClient(record_dir=out_dir)

    diagnostics_deps = AgentDeps(vehicle_data=_FixedVehicleData())
    final_state = await ask(client, diagnostics_deps, GOLDEN_DIAGNOSTICS_QUESTION)
    print(f"Recorded diagnostics scenario (route={final_state.get('route')}): {GOLDEN_DIAGNOSTICS_QUESTION!r}")

    async with async_session_factory() as session:
        await ingest_kb_directory(session, KB_DIR)  # idempotent, safe to re-run
        knowledge_deps = AgentDeps(vehicle_data=_FixedVehicleData(), kb=RepositoryKBSearchProvider(session))
        final_state = await ask(client, knowledge_deps, GOLDEN_KNOWLEDGE_QUESTION)
        print(
            f"Recorded knowledge scenario (route={final_state.get('route')}, "
            f"{len(final_state.get('citations') or [])} citation(s)): {GOLDEN_KNOWLEDGE_QUESTION!r}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Cassette directory to write into (default: {DEFAULT_OUT_DIR}).",
    )
    args = parser.parse_args()
    asyncio.run(record(args.out))


if __name__ == "__main__":
    main()
