# CLAUDE.md: project guide

## What this is
Multi-tenant AI Agent Automation SaaS. Agents run on Claude with tool use, orchestrated by
LangGraph, executed by Celery workers, stored in Postgres (Supabase). See `docs/architecture.md`
and `docs/er-diagram.md`.

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
Stack: `cp .env.example .env` then `docker compose up --build` (API :8000, web :3000).

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
- Tenant data is only touched through a session that called `use_tenant(...)` (see
  `docs/tenancy.md`). Never connect as the owner/superuser for request handling.
- Every tenant table has `org_id`. Every change to a model needs a migration (CI enforces it).
- No decorative UI: every control must work.
- Commit at logical milestones with clear messages.

## Phase status
- [x] Phase 1: Foundation (monorepo, API, worker, Docker, models, Alembic, CI, frontend shell)
- [x] Phase 2: Identity and tenancy: [x] 2A token verification, [x] 2B row level security,
      [x] 2C organizations/roles/invitations, [x] 2D login/register pages and app shell
- [ ] Phase 3: Agents and engine
- [ ] Phase 4: Tools and approvals (MVP)
