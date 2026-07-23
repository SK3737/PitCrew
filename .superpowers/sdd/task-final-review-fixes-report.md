# Final Whole-Branch Review Fixes

Fixes for the two findings from the final whole-branch review, against
worktree commit `652bf89` (branch `worktree-pitcrew-implementation`).

## Finding 1: `use_assistant_replay` didn't force replay mode

**Problem.** Both `POST /assistant/ask` and `POST /assistant/stream` guarded
with `require_permission("use_assistant", "use_assistant_replay")` but then
unconditionally called `build_default_client()`, which branches only on the
ambient `settings.LLM_BACKEND`. A `demo`-role caller (meant to hold only the
replay permission) would have transparently received a live `GroqClient` in
any deployment with `LLM_BACKEND=groq`, defeating the isolation the
permission name promises.

**Fix - `backend/app/routers/assistant.py`.**
Added a helper, called from both routes instead of `build_default_client()`
directly:

```python
def _llm_client_for_role(role: str) -> LLMClient:
    if "use_assistant" in ROLE_PERMISSIONS.get(role, frozenset()):
        return build_default_client()
    return ReplayClient()
```

- A role holding the full `use_assistant` permission (`mechanic`, `admin`)
  still gets whatever `LLM_BACKEND` says - unchanged behavior.
- A role holding only `use_assistant_replay` (`demo`) is now always forced
  onto `ReplayClient`, regardless of `LLM_BACKEND`.

Both `ask_assistant` and `stream_assistant` now call
`_llm_client_for_role(current_user.role)` in place of `build_default_client()`.
Imports were updated to pull in `LLMClient`, `ReplayClient`, and
`ROLE_PERMISSIONS`.

**Test evidence.**
Added to `backend/tests/test_assistant_route.py`:
- `test_demo_role_is_forced_onto_replay_client_even_when_backend_is_groq` -
  sets `settings.LLM_BACKEND = "groq"` via monkeypatch, monkeypatches
  `assistant_router.ask` to capture the `llm_client` instance passed in,
  logs in as `demo`, calls `/assistant/ask`, and asserts the captured
  client `isinstance(..., ReplayClient)`.
- `test_mechanic_role_honors_llm_backend_setting_when_set_to_groq` - same
  setup but role `mechanic`, asserts the captured client
  `isinstance(..., GroqClient)` (constructing `GroqClient()` with an empty
  `GROQ_API_KEY` does not make a network call or raise - verified directly
  against the installed `groq` SDK before writing the test).

Added the same pair of tests to `backend/tests/test_assistant_stream.py`
for the `/assistant/stream` sibling
(`test_stream_demo_role_is_forced_onto_replay_client_even_when_backend_is_groq`,
`test_stream_mechanic_role_honors_llm_backend_setting_when_set_to_groq`),
capturing the `llm_client` argument passed into a monkeypatched
`build_supervisor_graph` instead.

**Why this proves the fix (reasoning, not a literal revert-and-rerun).**
Pre-fix, both routes called `build_default_client()` unconditionally. With
`LLM_BACKEND` monkeypatched to `"groq"`, `build_default_client()` always
returns a `GroqClient` - for every role, including `demo`. The demo-role
tests' assertion `isinstance(captured["llm_client"], ReplayClient)` would
therefore have failed pre-fix (the captured client would have been a
`GroqClient` instead), and passes post-fix because `_llm_client_for_role`
special-cases `demo`. The mechanic-role tests pass both before and after
the fix (mechanic was never affected), which is exactly the "unaffected"
half of the finding's requested test.

## Finding 2: dead RBAC permissions removed

**Problem.** `backend/app/auth/rbac.py` declared `manage_own` (assigned to
`owner`) and `read_only` (assigned to `demo`) in `PERMISSIONS` and
`ROLE_PERMISSIONS`, but a repo-wide grep confirmed no route or dependency
anywhere checks either permission - pure unused scaffolding.

**Fix - `backend/app/auth/rbac.py`.**
Removed `manage_own` and `read_only` from the `PERMISSIONS` frozenset and
from `owner`'s and `demo`'s entries in `ROLE_PERMISSIONS`:

- `owner`: `{"read_own_vehicles", "manage_own"}` -> `{"read_own_vehicles"}`
- `demo`: `{"read_only", "use_assistant_replay"}` -> `{"use_assistant_replay"}`

`admin`'s entry (`PERMISSIONS`, the full set) shrinks accordingly - no
route depends on the removed names, and `admin`'s admin-only routes are
untouched since they don't check these permissions either.

**Verification nothing depended on them.** `grep -rn "manage_own|read_only"`
across the whole repository (before this change) found no reference
outside `backend/app/auth/rbac.py` and `backend/app/routers/assistant.py`'s
docstring (which only names `use_assistant`/`use_assistant_replay`, not the
two removed permissions). No test asserted the exact `PERMISSIONS`/
`ROLE_PERMISSIONS` contents, so nothing needed updating there.

One additional reference exists in `plan.md` (the original Phase 2 spec
checklist item, `2.6 Current-user dep + RBAC`, which lists `manage_own`/
`read_only` as part of the originally-planned role map) - left untouched
per this task's explicit scope restriction to
`backend/app/routers/assistant.py`, `backend/app/auth/rbac.py`, and their
tests only; `plan.md` is a historical planning artifact, not executable
code or a test asserting current behavior.

## Verification

1. **Full backend suite:** `cd backend && python -m pytest -q` ->
   **123 passed**, 1 pre-existing `langchain-community` deprecation
   warning, in 69.34s. No regressions from finding 2's removal.
2. **New/updated tests for finding 1:**
   `python -m pytest -q -k "demo_role_is_forced or mechanic_role_honors or stream_demo_role_is_forced or stream_mechanic_role_honors"`
   -> **4 passed**.
3. **Lint:** `python -m ruff check backend` -> **All checks passed!**

## Files changed

- `backend/app/routers/assistant.py` - added `_llm_client_for_role`, both
  routes now call it instead of `build_default_client()` directly.
- `backend/app/auth/rbac.py` - removed `manage_own` and `read_only` from
  `PERMISSIONS` and from `owner`'s/`demo`'s `ROLE_PERMISSIONS` entries.
- `backend/tests/test_assistant_route.py` - two new tests (demo forced to
  replay under `LLM_BACKEND=groq`; mechanic unaffected).
- `backend/tests/test_assistant_stream.py` - two new tests, same shape,
  for the `/assistant/stream` route.
