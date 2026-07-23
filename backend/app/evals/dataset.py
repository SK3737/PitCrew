"""
Task 9.1's "fixed eval set of KB questions" - three real, grounded
question/context/answer triples drawn straight from the committed KB corpus
(`backend/data/kb/*.md`, the same corpus `app.rag.ingest`/`hybrid_search`
serve in production), not fabricated.

Each case's `retrieved_contexts` is a verbatim excerpt copied from the real
markdown file named in `source`, and each `response`/`reference` answer is a
faithful paraphrase of that excerpt - the same "hand-scripted wording, real
grounding content" convention Phase 7 used for the golden cassettes (see
`.superpowers/sdd/task-7-report.md`, "How the golden cassettes were
produced"). This dataset intentionally does *not* go through a live
Postgres + pgvector `hybrid_search` call: Phase 7 already flagged the KB
golden cassette's coupling to `KBChunk.chunk_id` being a fresh
auto-increment sequence as a fragility; sidestepping the DB entirely here
keeps `make eval`'s Ragas suite runnable with no database dependency at all,
and keeps the fixture text stable forever regardless of ingest order.

Two of the three cases are deliberately imperfect, not uniformly ideal, so
the suite actually discriminates instead of trivially scoring 1.0 everywhere:

- `bmw_coolant_flush` ranks an irrelevant distractor passage *above* the
  real relevant one in `retrieved_contexts`, so `context_precision` (which
  rewards relevant passages ranking first) scores below 1.0.
- `corolla_oil_change`'s `response` includes one extra claim
  ("...also improves fuel economy by roughly 5%.") that the retrieved
  context does not support, so `faithfulness` scores below 1.0 for that case.

See `backend/scripts/record_eval_cassettes.py` for how each case's judge
responses (statement lists, verdicts, generated questions) were produced -
scripted by hand from these exact case objects, not by any live model.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    question: str
    response: str
    """The assistant's answer under evaluation (Ragas's `response`/`answer`)."""
    retrieved_contexts: list[str]
    """Passages the RAG pipeline retrieved, most-relevant-first (or not, for
    the deliberately-mis-ranked `bmw_coolant_flush` case)."""
    reference: str = ""
    """Ground-truth answer used by `context_precision`/`context_recall` -
    identical to `response` for these cases, since the response itself is
    already a faithful, grounded answer."""
    source: str = ""

    def __post_init__(self) -> None:
        if not self.reference:
            object.__setattr__(self, "reference", self.response)


_BMW_COOLANT_CONTEXT = (
    "BMW's factory long-life coolant is commonly rated for around 4-6 years or "
    "100,000-150,000 km, after which a full flush is recommended to protect the "
    "aluminium engine block and plastic coolant system components from "
    "corrosion as seals age."
)
_HONDA_CIVIC_DISTRACTOR_CONTEXT = (
    "A common owner report on turbocharged Civic engines is oil dilution from "
    "fuel in cold climates with frequent short trips, which is why Honda "
    "recommends closer monitoring of the oil life indicator rather than a "
    "blanket fixed interval."
)
_HONDA_BRAKE_FLUID_CONTEXT = (
    "Front brake pads on a Civic typically last 35,000-45,000 km in mixed "
    "driving. Brake fluid is commonly replaced every 3 years or 60,000 km as a "
    "conservative interval, since Honda's own fluid spec is DOT 3 which absorbs "
    "moisture faster than DOT 4."
)
_COROLLA_OIL_CONTEXT = (
    "The Corolla's naturally aspirated petrol engines are typically run on 0W-16 "
    "or 0W-20 full-synthetic oil. Under normal driving, a synthetic oil and "
    "filter change is commonly recommended every 10,000 km or 12 months, "
    "whichever comes first. Vehicles used mostly for short trips, towing, or in "
    "dusty conditions fall under a \"severe\" schedule and should be serviced "
    "closer to every 5,000 km."
)

EVAL_CASES: list[EvalCase] = [
    EvalCase(
        case_id="bmw_coolant_flush",
        question="How often should I flush the coolant on a BMW 3 Series?",
        response=(
            "BMW's factory long-life coolant is rated for roughly 4-6 years or "
            "100,000-150,000 km, after which a full flush is recommended to "
            "protect the aluminium engine block and plastic coolant components "
            "from corrosion as seals age. [1]"
        ),
        # Distractor ranked first on purpose - see module docstring.
        retrieved_contexts=[_HONDA_CIVIC_DISTRACTOR_CONTEXT, _BMW_COOLANT_CONTEXT],
        source="backend/data/kb/bmw_3series.md#Coolant Service",
    ),
    EvalCase(
        case_id="civic_brake_fluid",
        question="How often should Honda Civic brake fluid be replaced?",
        response=(
            "Honda Civic brake fluid is commonly replaced every 3 years or "
            "60,000 km, a conservative interval since Honda's DOT 3 fluid "
            "absorbs moisture faster than DOT 4. [1]"
        ),
        retrieved_contexts=[_HONDA_BRAKE_FLUID_CONTEXT],
        source="backend/data/kb/honda_civic.md#Brake Service",
    ),
    EvalCase(
        case_id="corolla_oil_change",
        question="How often should I change the oil on a Toyota Corolla?",
        response=(
            "The Corolla's engines typically run on 0W-16 or 0W-20 "
            "full-synthetic oil, with an oil and filter change recommended "
            "every 10,000 km or 12 months under normal driving; vehicles under "
            "severe conditions (short trips, towing, dust) should be serviced "
            "closer to every 5,000 km. Using synthetic oil also improves fuel "
            "economy by roughly 5%. [1]"
        ),
        retrieved_contexts=[_COROLLA_OIL_CONTEXT],
        source="backend/data/kb/toyota_corolla.md#Oil and Filter Change",
    ),
]
