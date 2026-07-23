"""
Optional Langfuse Cloud tracing hook for the supervisor graph (Phase 9,
task 9.3 - relocated here from `app.agents.tracing`, its original home from
the phase that first wired the supervisor up to it, so this module now
lives where the brief expects observability code to live).

Best-effort only: Langfuse is observability, never a hard dependency for
the graph to run. If `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` aren't set
(the Phase 1 default - both empty strings, and the default in every
environment this project runs in today, since no Langfuse Cloud account
exists here) `trace_span` is a no-op context manager, and the graph behaves
exactly as if `langfuse` weren't installed. Any failure to initialize or
emit a span - bad credentials, an unreachable host, a client-library bug -
is caught and logged, never raised: a tracing outage must never turn into
an assistant-request failure. See `backend/tests/test_observability_langfuse.py`
for the tests that pin this fail-open contract, including a case that
force-enables the client with garbage credentials and confirms `trace_span`
still yields cleanly.

Each span is tagged with the supervisor's own `run_id` (see
`app.agents.supervisor.SupervisorState`) via the `metadata` dict passed to
`start_as_current_observation`, so a real Langfuse Cloud project - once a
human wires up real credentials - can correlate every node's span back to
one end-to-end assistant call.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _build_client(public_key: str, secret_key: str, host: str) -> tuple[Optional[Any], bool]:
    """Construct the Langfuse client from explicit credentials.

    Factored out of module-import time so `backend/tests/test_observability_langfuse.py`
    can exercise both fail-open branches directly (blank keys -> no-op;
    configured-but-broken -> caught, disabled) without needing to reload
    this module or monkeypatch `app.config.settings` - the production path
    below still only ever calls this once, at import, exactly as before.
    """
    if not (public_key and secret_key):
        return None, False
    try:
        from langfuse import Langfuse

        client = Langfuse(public_key=public_key, secret_key=secret_key, host=host or None)
        return client, True
    except Exception:  # noqa: BLE001 - tracing must never break the graph
        logger.warning("Langfuse configured but failed to initialize; tracing disabled.", exc_info=True)
        return None, False


_client, _enabled = _build_client(settings.LANGFUSE_PUBLIC_KEY, settings.LANGFUSE_SECRET_KEY, settings.LANGFUSE_HOST)


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
