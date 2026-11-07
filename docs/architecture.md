# Architecture

## Components

```
Browser ──▶ Next.js (Vercel)            Supabase Auth (JWT issuer)
   │                                          │
   └──────────▶ FastAPI API (Render) ◀────────┘  verifies JWTs
                  │        │
                  │        └──▶ Redis ◀──▶ Celery workers ──▶ Claude API, external tools
                  ▼                              │
            PostgreSQL (Supabase, pgvector) ◀────┘
```

- **Web:** Next.js 16, React, Tailwind, shadcn/ui, TanStack Query.
- **API:** FastAPI. Layers: routers, services, repositories. No logic in `main.py`.
- **Workers:** Celery on Redis run agent executions, schedules and webhooks.
- **Engine (Phase 3):** LangGraph loop: load agent, call Claude, validate tool call, check policy,
  execute or pause for approval, repeat within iteration, time, token and cost limits.
- **Database:** PostgreSQL. Alembic migrations. See `er-diagram.md`.

## Key decisions

1. **Supabase Auth.** Registration, login, verification and password reset are not hand-rolled.
   The API only verifies JWTs and maps `sub` to a local `users` row.
2. **Tenant isolation in two layers.** Application queries are scoped by `org_id`; Postgres Row
   Level Security enforces it with a per-transaction `app.org_id` setting and a non-superuser
   runtime role. Composite foreign keys `(id, org_id)` stop a row linking to another tenant's data.
3. **Approvals never hold a worker.** A run needing approval persists its checkpoint, frees the
   worker, and resumes as a new task when someone decides.
4. **No code execution.** Agents never run AI-generated code or shell commands. Tool arguments from
   the model are validated against each tool's schema before use.
5. **Least privilege.** Agents get only granted tools. The runtime DB role cannot modify the audit
   log or the tool catalog.

## Environments

- **Local:** Docker Compose (db, redis, api, worker, frontend).
- **CI:** GitHub Actions: backend (lint, types, migrations, tests), frontend, e2e, docker build.
- **Production (Phase 8):** Vercel (web), Render (API and workers), Supabase (database, auth).
