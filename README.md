# AI Agent Platform

A multi-tenant SaaS where businesses create AI agents that do real work (send Slack messages, call APIs, open GitHub issues, draft emails) through controlled integrations, with humans approving anything sensitive.

## How it works

1. **Create an agent**: give it a name, instructions, a Claude model, and a list of tools it may use.
2. **Run it**: manually, from the playground, or later on a schedule or webhook.
3. **The engine loops**: it sends the task to Claude, Claude asks to use a tool, the platform validates the request, checks permissions and policy, runs it, and feeds the result back, until the task is done or a limit is hit.
4. **Approvals**: sensitive actions (sending messages, deleting data, payments) pause the run until a person approves or rejects.
5. **Monitor**: every step, tool call, token and cost estimate is recorded and visible.

## Status

Phase 1 (foundation) in progress. See `CLAUDE.md` for conventions and `docs/` for architecture.

## Structure

- `backend/`: FastAPI, SQLAlchemy, Alembic, engine, tools, workers
- `frontend/`: Next.js app
- `infrastructure/`: Docker, Render, Supabase config
- `docs/`: architecture, ER diagram, decisions
- `scripts/`: dev helper scripts
- `tests/e2e/`: Playwright end-to-end tests
