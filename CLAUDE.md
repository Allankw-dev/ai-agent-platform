# CLAUDE.md: project guide

## What this is
Multi-tenant AI Agent Automation SaaS. Agents run on Claude with tool use, orchestrated by LangGraph, executed by Celery workers, stored in Postgres (Supabase).

## Key decisions
- Auth: Supabase Auth. FastAPI only verifies JWTs and maps them to local users.
- Isolation: every query scoped by org_id in the app AND Postgres RLS (`SET LOCAL app.org_id` per transaction, non-superuser DB role).
- Approvals: persist run state, release the worker, resume via a new Celery task.
- MVP = Phases 1-4. Do not start later phases before the current one is tested.
- Develop in Linux/WSL2. Docker Compose runs the stack.

## Conventions
- Python 3.12, Ruff, mypy, pytest. TypeScript strict, ESLint, Vitest, Playwright.
- No logic in `main.py`. Routers -> services -> repositories.
- Never trust model-generated tool arguments; validate against the tool schema.
- No secrets in code. Config via environment only.
- Commit at logical milestones with clear messages.

## Phase status
- [ ] Phase 1: Foundation
- [ ] Phase 2: Identity and tenancy
- [ ] Phase 3: Agents and engine
- [ ] Phase 4: Tools and approvals (MVP)
