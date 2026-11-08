# AI Agent Platform

A multi-tenant SaaS where businesses create AI agents that do real work (send Slack messages, call
APIs, open GitHub issues, draft emails) through controlled integrations, with humans approving
anything sensitive.

## How it works

1. **Create an agent**: name, instructions, a Claude model, and the tools it may use.
2. **Run it**: manually, from the playground, or later on a schedule or webhook.
3. **The engine loops**: Claude asks to use a tool, the platform validates the request, checks
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

- Web: http://localhost:3000 (create an account at /register; status page at /status)
- API docs: http://localhost:8000/api/docs
- Tests: `docker compose exec api pytest`

## Status

Phases 1 (foundation) and 2 (accounts, organizations, roles, invitations) complete. See `CLAUDE.md` for conventions and commands, and `docs/` for the
architecture and ER diagram.

## Structure

- `backend/`: FastAPI, SQLAlchemy, Alembic, Celery workers
- `frontend/`: Next.js app
- `infrastructure/`: Docker and deployment config
- `docs/`: architecture, ER diagram
