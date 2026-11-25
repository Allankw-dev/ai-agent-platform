# CLAUDE.md: project guide

## What this is
Multi-tenant AI Agent Automation SaaS. Agents run on an LLM provider with tool use (Gemini first, provider-agnostic
engine), orchestrated by LangGraph, executed by Celery workers, stored in Postgres (Supabase). See `docs/architecture.md`
and `docs/er-diagram.md`.

## Roadmap
The plan for everything after Phase 4 is in `docs/MASTER_BUILD_INSTRUCTION.md` (revised). Follow its
phase order and engineering rules. Where it and this file disagree, ask.

## Key decisions
- Auth: Supabase Auth. FastAPI only verifies JWTs and maps them to local users.
- Isolation, two layers: every query is scoped by `org_id` in the app, and Postgres Row Level
  Security enforces it (`SET LOCAL app.org_id` per transaction, non-superuser runtime role
  `agent_app`). Child tables reference parents by `(id, org_id)` so cross-tenant links are
  impossible at the database level.
- Approvals: persist run state, release the worker, resume via a new Celery task.
- MVP = Phases 1-4. Do not start a later phase before the current one is tested.
- Develop in Linux/WSL2 or Docker. Docker Compose runs the stack.

## Commands
Stack: `cp .env.example .env` then `docker compose up --build` (API :8000, web :3000; both changeable with `API_PORT` / `WEB_PORT` in `.env`).

Backend (in `backend/`, Python 3.12 pinned, managed by uv):
- `uv sync`, `uv run ruff check .`, `uv run ruff format .`, `uv run mypy app tests`
- `docker compose exec api alembic upgrade head`, `alembic check` (models vs migrations)
- `docker compose exec api pytest` (database tests need Postgres; CI sets `REQUIRE_DB=1`)
- New migration: `docker compose exec api alembic revision --autogenerate -m "message"`, then
  review the file by hand (autogenerate misses things such as circular foreign keys).

Frontend (in `frontend/`, Node 22, Next.js 16 with Cache Components enabled):
- `npm run dev | lint | typecheck | format:check | test | build | test:e2e`
- The browser calls the API at `NEXT_PUBLIC_API_URL` (default http://localhost:8000).
- Sign-in uses Supabase from the browser (`NEXT_PUBLIC_SUPABASE_URL` and the publishable key);
  see `docs/auth.md`. Pages under `src/app/(app)` require sign-in; `(marketing)` and `(auth)` do not.
- Components that read the URL (`useSearchParams`, `usePathname`) need a `<Suspense>` boundary
  (Cache Components); `next build` fails otherwise.

## Conventions
- Python 3.12, Ruff, strict mypy, pytest. TypeScript strict, ESLint, Prettier, Vitest, Playwright.
- No logic in `main.py`. Routers -> services -> repositories.
- Never trust model-generated tool arguments; validate against the tool schema.
- No secrets in code. Config via environment only. Never commit `.env`.
- Stored secrets (integration credentials) are write-only: only `app/services/credentials.py`
  decrypts them, no response, log, audit entry or run step may contain one, and tool output goes
  through `redact_secret` first (see `docs/credentials.md`; tests enforce the structure).
- Tenant data is only touched through a session that called `use_tenant(...)` (see
  `docs/tenancy.md`). Never connect as the owner/superuser for request handling.
- Every tenant table has `org_id`. Every change to a model needs a migration (CI enforces it).
- Anything that grants access because of someone's email address must use `ConfirmedUser`, not
  `CurrentUser` (the token's email claim does not prove the address was confirmed).
- Every change to a run's state (started, finished, cancelled, paused, resumed, a step, an approval)
  writes a run event in the same transaction through `run_events.emit`. Event `data` holds ids and
  statuses only, never tool arguments, tool output or message text (see `docs/engine.md`).
- Delivering changes as zips: a zip cannot delete files, so list deleted or moved files explicitly.
- No decorative UI: every control must work.
- Commit at logical milestones with clear messages.

## Phase status
- [x] Phase 1: Foundation (monorepo, API, worker, Docker, models, Alembic, CI, frontend shell)
- [x] Phase 2: Identity and tenancy: [x] 2A token verification, [x] 2B row level security,
      [x] 2C organizations/roles/invitations, [x] 2D login/register pages and app shell
- [x] Phase 3: Agents and engine: [x] 3A agents and versions, [x] 3B engine (Gemini), [x] 3C runs API,
      [x] 3D frontend (agent screens, run screens)
- [x] Phase 4: Tools and approvals (MVP). Design in `docs/phase4-design.md`, approved (all seven
      decisions accepted as recommended). [x] 4A vault and Integrations tab, [x] 4B HTTP tools,
      [x] 4C Slack, [x] 4D approvals backend, [x] 4E approval screens, [x] 4F acceptance and cleanup
- [ ] Phase 5: Run reliability and quotas. Design in `docs/phase5-design.md`, approved (all eight
      decisions accepted as recommended). [x] 5A run events and streaming (built, awaiting
      acceptance), [ ] 5B limits and quotas, [ ] 5C crash recovery, [ ] 5D observability and audit,
      [ ] 5E emergency stop
