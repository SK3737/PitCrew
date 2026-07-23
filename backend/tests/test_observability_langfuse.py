"""
Task 9.3: `app.observability.langfuse` must fail open in every scenario -
never turn a tracing problem into an assistant-request failure.

Three scenarios covered, matching the brief's explicit "confirm the graph
still runs correctly end-to-end with Langfuse 'enabled' in code but pointed
at no real credentials" requirement:

1. Blank keys (this environment's actual default, per `app.config.settings`
   - no Langfuse Cloud account exists here) -> `trace_span` is a pure no-op,
   confirmed by asserting the module's own `_enabled` flag is `False` and
   that `trace_span` still yields control to its `with` block.
2. Keys present but the `Langfuse(...)` constructor itself raises (garbage
   host/invalid credentials) -> caught inside `_build_client`, client stays
   `None`, tracing disabled - never propagates.
3. A client that constructs fine but whose `start_as_current_observation`
   raises at span-start time (e.g. an unreachable ingestion host) -> caught
   inside `trace_span` itself, the `with` block's body still runs.

None of these ever raise out of `trace_span`, and the full supervisor graph
is also driven end-to-end (against a golden replay cassette) with a broken
client force-installed, proving a tracing outage cannot break `/assistant/ask`.
"""

from __future__ import annotations

from pathlib import Path

import app.observability.langfuse as langfuse_module
from app.agents.llm_client import ReplayClient
from app.agents.supervisor import ask
from app.agents.tools import AgentDeps, VehicleServiceSnapshot

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "cassettes" / "golden"


class _GoldenVehicleData:
    async def get_snapshot(self, vehicle_id: str):
        if vehicle_id != "V001":
            return None
        return VehicleServiceSnapshot(
            vehicle_id="V001",
            months_driven=5.0,
            kms_driven=6000.0,
            make="Toyota",
            vehicle_model="Corolla",
            year=2020,
            fuel_type="petrol",
            last_service_type="oil_change",
        )


def test_blank_credentials_are_the_ambient_default_and_disable_tracing():
    """This environment's actual `app.config.settings` (no Langfuse Cloud
    account exists here) - the module-import-time state must reflect that."""
    assert langfuse_module._enabled is False
    assert langfuse_module._client is None


def test_build_client_noops_on_blank_keys():
    client, enabled = langfuse_module._build_client("", "", "")
    assert client is None
    assert enabled is False


def test_build_client_fails_open_when_constructor_raises(monkeypatch):
    """Keys are non-blank (so this project's code path attempts to build a
    real client) but the underlying `Langfuse(...)` constructor itself
    raises - simulating a garbage host or invalid credential shape."""

    class _BrokenLangfuse:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("simulated: invalid Langfuse Cloud credentials")

    import langfuse

    monkeypatch.setattr(langfuse, "Langfuse", _BrokenLangfuse)

    client, enabled = langfuse_module._build_client("pk-fake", "sk-fake", "https://not-a-real-host.invalid")

    assert client is None
    assert enabled is False


def test_trace_span_is_a_pure_noop_when_disabled():
    ran = False
    with langfuse_module.trace_span("some_node", run_id="run-123"):
        ran = True
    assert ran is True


def test_trace_span_fails_open_when_the_client_raises_at_span_start(monkeypatch):
    """Force-enable tracing with a client whose `start_as_current_observation`
    raises (e.g. an unreachable ingestion endpoint at request time, distinct
    from a constructor-time failure) - `trace_span`'s own try/except must
    still let the wrapped code run and must not propagate the exception."""

    class _RaisingObservation:
        def __enter__(self):
            raise RuntimeError("simulated: Langfuse ingestion host unreachable")

        def __exit__(self, *exc_info):
            return False

    class _RaisingClient:
        def start_as_current_observation(self, name, metadata=None):
            return _RaisingObservation()

    monkeypatch.setattr(langfuse_module, "_client", _RaisingClient())
    monkeypatch.setattr(langfuse_module, "_enabled", True)

    ran = False
    with langfuse_module.trace_span("some_node", run_id="run-456"):
        ran = True
    assert ran is True


async def test_supervisor_graph_still_completes_when_langfuse_is_enabled_but_broken(monkeypatch):
    """End-to-end proof: force-enable Langfuse with a client that raises on
    every span, then run the real golden diagnostics scenario through the
    real supervisor graph. The assistant call must complete successfully and
    produce the exact same answer as with tracing disabled - a tracing
    outage must never surface as a broken `/assistant/ask` response."""

    class _RaisingObservation:
        def __enter__(self):
            raise RuntimeError("simulated: Langfuse ingestion host unreachable")

        def __exit__(self, *exc_info):
            return False

    class _RaisingClient:
        def start_as_current_observation(self, name, metadata=None):
            return _RaisingObservation()

    monkeypatch.setattr(langfuse_module, "_client", _RaisingClient())
    monkeypatch.setattr(langfuse_module, "_enabled", True)

    replay = ReplayClient(cassette_dir=GOLDEN_DIR)
    deps = AgentDeps(vehicle_data=_GoldenVehicleData())

    final_state = await ask(replay, deps, "When does V001 need its next service?")

    assert final_state["route"] == "diagnostics"
    assert final_state["tool_results"]["predict_service"]["vehicle_id"] == "V001"
    assert "38" in final_state["answer"]
