# ADR 0004: Deploy stack - Neon, Render, Vercel, Langfuse Cloud, GitHub Actions

## Status

Accepted as design; infrastructure-as-code written and locally verified in Phase 9.
**Not yet deployed** - see "Consequences" below and the [deployment checklist](../../README.md#deployment-checklist) in the README for exactly what is still pending.

## Context

The project's non-goals rule out a full MLOps platform (no Kubernetes, no Terraform, no self-managed database or observability stack) - the explicit ceiling is docker-compose for local dev plus managed, free-tier hosts for the live demo.
Three deployables need a home: Postgres with pgvector, the FastAPI backend, and the Next.js frontend, plus an observability sink for agent traces.

## Decision

- **Database**: Neon Postgres with the pgvector extension, chosen because its free tier does not expire on a timer and its scale-to-zero resume is on the order of a second, which matters for a demo that will sit idle between reviewers.
- **Backend**: Render's free web service tier, running the same Docker image as local dev, with `LLM_BACKEND=groq` so the public demo is a genuinely live assistant, not a replay-only shell.
  `render.yaml` is a Render Blueprint: Docker runtime, `preDeployCommand: python -m alembic upgrade head` so migrations run automatically before each deploy is promoted, and every `envVars` key traced to a real field `app.config.Settings` reads.
- **Frontend**: Vercel's Hobby tier, deployed from `frontend/vercel.json` (a minimal, standard Next.js config with no secrets committed - `BACKEND_URL`/`SESSION_SECRET` are set via Vercel's own dashboard/CLI).
- **Observability**: Langfuse Cloud's free tier, not a self-hosted Langfuse instance, so no additional service needs to be operated in production.
- **CI/CD**: GitHub Actions. `ci.yml` (lint, backend tests, frontend build, Playwright e2e, eval gate) is real and runs on every push/PR against replay-mode fixtures, no secrets required. `deploy.yml` triggers a Render deploy hook and a Vercel CLI deploy on push to `main`, but every step defensively checks for a blank secret and exits 0 (no-op) rather than failing, so merging it today is safe and it starts working the moment real secrets are added.

## Consequences

**Positive**:
The whole stack is genuinely free at this project's scale, with no infrastructure to patch or babysit beyond the four managed services themselves, and the IaC files are ready to activate with no further code changes once accounts exist.
`render.yaml`'s Docker image was actually built and run locally end to end (`docker build` + `docker run` + `curl /health`), which caught and fixed two real, pre-existing bugs before any deploy attempt: a `Dockerfile` missing several `COPY` lines (migrations and the KB corpus could never have run in a container built from it), and an unpinned `pydantic-ai` dependency that silently resolved to an 18-major-version-old, broken release on a genuinely fresh install (exactly what `docker build` and a fresh CI runner both do), which would have made `ci.yml`'s very first step install a broken app.

**Negative - the honest, current state**:
**Nothing in this stack has actually been deployed.**
No Neon, Render, Vercel, or Langfuse Cloud account exists as of this writing, no live URL exists, and no real Langfuse trace has ever been captured.
Everything above was verified as far as it can be without those accounts: a real local Docker build/run cycle for the backend image, and every env var and command checked against the real settings/health-check contract, but not against Render's or Vercel's actual build environment, quotas, or network.
A known, unresolved risk going into that first real deploy: the Docker image pulls in `torch`'s default CUDA/GPU wheel via `sentence-transformers`, even though this project's design is explicitly CPU-only inference everywhere - the resulting image is large enough that it may not fit Render's free-tier build time or memory limits as currently pinned, and a future change should pin `torch`'s CPU-only wheel index in `backend/requirements.txt` before attempting the real deploy.
Render's free tier also cold-starts its container after idle; the design anticipates a scheduled keep-warm ping but that ping is not yet wired up anywhere.
See the README's [deployment checklist](../../README.md#deployment-checklist) for the concrete list of what a human still needs to do by hand.
