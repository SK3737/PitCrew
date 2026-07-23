"""
Optional Langfuse tracing hook for the supervisor graph.

Best-effort only: Langfuse is observability, never a hard dependency for
the graph to run. If `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` aren't set
(the Phase 1 default - both empty strings) `trace_span` is a no-op context
manager, and the graph behaves exactly as if `langfuse` weren't installed.
Any failure to initialize or emit a span is caught and logged, never raised
- a tracing outage must not turn into a request failure.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_client = None
_enabled = bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)

if _enabled:
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST or None,
        )
    except Exception:  # noqa: BLE001 - tracing must never break the graph
        logger.warning("Langfuse configured but failed to initialize; tracing disabled.", exc_info=True)
        _client = None
        _enabled = False


@contextmanager
def trace_span(name: str, *, run_id: Optional[str] = None, **metadata: Any) -> Iterator[None]:
    """Best-effort tracing span around a supervisor graph node. No-ops
    entirely when Langfuse isn't configured; never raises on tracing failure."""
    if not _enabled or _client is None:
        yield
        return
    try:
        with _client.start_as_current_observation(name=name, metadata={"run_id": run_id, **metadata}):
            yield
    except Exception:  # noqa: BLE001
        logger.warning("Langfuse span %r failed; continuing without tracing.", name, exc_info=True)
        yield
