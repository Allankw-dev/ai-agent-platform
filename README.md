# AI Agent Platform

A multi-tenant SaaS where businesses create AI agents that do real work (send Slack messages, call
APIs, open GitHub issues, draft emails) through controlled integrations, with humans approving
anything sensitive.

## How it works

1. **Create an agent**: name, instructions, a model (Gemini today; the engine is provider-agnostic), and
   the tools it may use.
2. **Run it**: manually, from the playground, or later on a schedule or webhook.
3. **The engine loops**: the model asks to use a tool, the platform validates the request, checks
   permissions and policy, runs it, and feeds the result back until the task is done or a limit hits.
4. **Approvals**: sensitive actions pause the run until a person approves or rejects.
5. **Monitor**: every step, tool call, token and cost estimate is recorded and visible.

## Quick start

Requires Docker Desktop.

```
cp .env.example .env
docker compose up --build
docker compose exec api alembic upgrade head
```

To save integration secrets (Integrations tab), generate an encryption key once and put it in `.env`
as `CREDENTIAL_ENCRYPTION_KEY` (never commit it), then recreate the containers:

```
docker compose exec api python -m app.core.vault
docker compose up -d --force-recreate api worker
```

- Web: http://localhost:3000 (create an account at /register; status page at /status)
- API docs: http://localhost:8000/api/docs
- Ports in use by another program? Set `WEB_PORT`, `API_PORT`, `DB_PORT` or `REDIS_PORT` in `.env`
  (see `.env.example`) and run `docker compose up -d`. The links above then use your port.
- Tests: `docker compose exec api pytest`

## Status

Phases 1 (foundation), 2 (accounts, organizations, roles, invitations) and 3 (agents, engine, runs)
are complete. Phase 4 (tools and approvals) is in progress: step 4A (credential vault, Integrations tab) is
done and step 4B (HTTP tools) is built. See `CLAUDE.md` for conventions and commands, and `docs/` for the
architecture, ER diagram and the Phase 4 design.

## Structure

- `backend/`: FastAPI, SQLAlchemy, Alembic, Celery workers
- `frontend/`: Next.js app
- `infrastructure/`: Docker and deployment config
- `docs/`: architecture, ER diagram
