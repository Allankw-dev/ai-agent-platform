# AI Agent Platform.

A multi-tenant SaaS where businesses create AI agents that do real work (send Slack messages, call
APIs, open GitHub issues, draft emails) through controlled integrations, with humans approving
anything sensitive.

## How it works

<<<<<<< HEAD
1. **Create an agent**: give it a name, instructions, a Claude model, and a list of tools it may use.
2. **Run it**: manually, from the playground, or later on a. schedule or webhook.
3. **The engine loops**: it sends the task to Claude, Claude asks to use a tool, the platform validates the request, checks permissions and policy, runs it, and feeds the result back, until the task is done or a limit is hit.
4. **Approvals**: sensitive actions (sending messages, deleting data, payments) pause the run until a person approves or rejects.
=======
1. **Create an agent**: name, instructions, a Claude model, and the tools it may use.
2. **Run it**: manually, from the playground, or later on a schedule or webhook.
3. **The engine loops**: Claude asks to use a tool, the platform validates the request, checks
   permissions and policy, runs it, and feeds the result back until the task is done or a limit hits.
4. **Approvals**: sensitive actions pause the run until a person approves or rejects.
>>>>>>> 1ccade4 (feat(frontend): Next.js shell, landing page, live status page, CI and docs)
5. **Monitor**: every step, tool call, token and cost estimate is recorded and visible.

## Quick start

Requires Docker Desktop.

```
cp .env.example .env
docker compose up --build
docker compose exec api alembic upgrade head
```

- Web: http://localhost:3000 (status page at /status)
- API docs: http://localhost:8000/api/docs
- Tests: `docker compose exec api pytest`

## Status

Phase 1 (foundation) complete. See `CLAUDE.md` for conventions and commands, and `docs/` for the
architecture and ER diagram.

## Structure

- `backend/`: FastAPI, SQLAlchemy, Alembic, Celery workers
- `frontend/`: Next.js app
- `infrastructure/`: Docker and deployment config
- `docs/`: architecture, ER diagram
