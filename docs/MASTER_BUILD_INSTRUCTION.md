# AI AGENT AUTOMATION PLATFORM: MASTER BUILD INSTRUCTION (REVISED)

Revision of the original 14-phase master instruction, rebased on the repository as it stands
(Phases 1 to 4E built) and on the decisions already taken. Read `CLAUDE.md` and `docs/` first.
Where this file and `CLAUDE.md` disagree, stop and ask.

You act as principal architect, senior AI engineer, distributed-systems engineer, security
engineer and database architect on an existing codebase. Extend it. Do not rewrite it.

---

## 1. What exists (do not rebuild)

- Monorepo `ai-agent-platform`: `backend/` (FastAPI, SQLAlchemy 2, Alembic, Celery, LangGraph),
  `frontend/` (Next.js 16, React 19, Tailwind, shadcn/ui, TanStack Query), `infrastructure/`,
  `docs/`, `scripts/`, `.github/workflows/ci.yml`.
- Auth: Supabase Auth; the API only verifies JWTs. `ConfirmedUser` for anything granted by email.
- Tenancy: `org_id` on every tenant table, composite `(id, org_id)` foreign keys, Row Level
  Security with `SET LOCAL app.org_id`, non-superuser runtime role `agent_app`.
- Roles: owner > admin > developer > member. Invitations. Audit log (append-only).
- Agents: immutable versions, rollback, duplicate, soft delete, per-version limits capped by
  platform ceilings.
- Engine: Gemini behind an `LLMClient` interface; LangGraph loop; runs and steps recorded as they
  happen; usage records; cost estimates from `MODEL_PRICES`; idempotency keys; orphaned-run cleanup.
- Tools: catalog in the database, handlers in Python, JSON-schema validation of model arguments,
  argument preparers. Built-ins, `http.get`, `http.request`, `slack.send_message`.
- Credential vault: AES-256-GCM, write-only secrets, redaction, only `services/credentials.py`
  decrypts.
- Approvals: pause with checkpoint, release the worker, atomic decide, resume as a new Celery task,
  expiry, cancel, approval screens.

Existing decisions stand: Supabase Auth and RLS, Gemini first with a provider-agnostic engine,
Celery on Redis, modular monolith, routers -> services -> repositories, no logic in `main.py`.

---

## 2. Changes from the original instruction (and why)

| Original | Now | Reason |
| --- | --- | --- |
| 24 workflow node types | About 9: manual, schedule and webhook triggers, agent, tool, condition, parallel and merge, approval, end | Add others only when a real workflow needs one. |
| Custom Python and TypeScript tools | OpenAPI tool import plus an MCP client. No code execution in the application process. A sandbox only if later proven necessary. | Most of the extensibility, far less risk. |
| Projects and environments | Deferred. The organization is the isolation boundary. "Stage" becomes a field on a deployment. | RLS and every query already key on `org_id`. |
| Marketplace | Deferred. Only a package manifest format. | Needs everything else first. |
| Hand-written SDKs | Generated from the OpenAPI schema; the CLI is a thin wrapper over the Python SDK | Hand-written SDKs drift. |
| Password hashing, email verification, MFA | Handled by Supabase; MFA is a setting to enable later | Do not rebuild auth. |
| Billing early | After quotas. Meter and limit first, then Stripe and M-Pesa | Limits come before payments. |
| 16 mandatory docs | Update the existing `docs/` and add a file only for a feature that exists | No empty documents. |

---

## 3. Added requirements (new, and important)

1. **Run event log.** Append-only table with a per-run sequence number. It powers streaming (SSE)
   with reconnect by last sequence id, replay and audit. Steps remain as they are.
2. **Quotas and concurrency before any automatic trigger.** Atomic reservation in Postgres
   (never in-memory counters): organization, agent and provider concurrency, plus daily token and
   cost quotas. Provider limits must respect Gemini free-tier 429s. Reserve before a run, settle
   after it. Simultaneous launches must not exceed a limit.
3. **More run limits.** Add `max_tool_calls` and delegation depth to the existing iterations,
   time, tokens and cost.
4. **Checkpoint recovery.** Checkpoint at each iteration boundary. A crashed run may resume and
   retry only steps with no side effects. A side-effect step that has started is never retried; the
   run reports plainly that it is unknown whether the action happened (existing behaviour).
5. **Approvals follow the root run.** Child runs carry `parent_run_id` and inherit the root's
   approval policy and budget. Delegation can never bypass an approval.
6. **Approval notifications** (Slack and email) and an optional organization setting: the
   approver cannot be the person who started the run.
7. **Organization kill switch.** Pause all runs, and disable an integration or tool instantly.
8. **Untrusted-output wrapper for every tool result and retrieved document**, not only `http.get`.
   Instructions inside tool output or knowledge are never followed.
9. **Retention and redaction policy** for run inputs and outputs, configurable per organization.
10. **Observability.** Structured logs, Sentry and OpenTelemetry traces wired through API,
    worker and engine, with secrets redacted.

---

## 4. Phases

Do one phase at a time. Within a phase, work in lettered steps (5A, 5B, ...). Do not start a phase
before the current one is tested and accepted by me. The application must run after every step.

### Phase 4F: acceptance and cleanup
- Run the full backend and frontend test suites and the Playwright run; fix what fails.
- Remove `battery-report.html` from the repo root.
- Fix doc drift: README and `CLAUDE.md` status for 4E; `docs/architecture.md` and any other text
  that says the engine calls Claude (it is Gemini; Anthropic is not implemented).
- Walk the approval flow by hand with `scripts/try-approval.ps1` and the UI.
- Accept when: all tests pass, docs match the code, I confirm.

### Phase 5: run reliability and quotas
- 5A Run event log, SSE endpoint with sequence ids and reconnect, frontend run page switched from
  polling to the stream (keep polling as a fallback).
- 5B Quotas and concurrency (section 3.2), `max_tool_calls`, delegation-depth field (unused until
  Phase 8), usage page backed by real data.
- 5C Checkpoint recovery (3.4), retry policy per tool with idempotency for retried side effects.
- 5D Sentry and OpenTelemetry (3.10); audit coverage review of every sensitive operation.
- 5E Organization kill switch (3.7).
- Tests: simultaneous run creation against a quota, duplicate queue delivery, two workers
  claiming one run, worker killed mid-run, stream reconnect, retry storm against a 429.
- Accept when: limits hold under concurrent load in tests and a killed worker leaves no stuck run.

### Phase 6: triggers, deployments and minimal evaluations
- 6A Schedules: cron with time zones, missed-run visibility, duplicate protection.
- 6B Webhooks: per-webhook secret, HMAC signature with timestamp tolerance, replay protection,
  event dedupe, payload size limit.
- 6C API keys (hashed, scoped, rotate, revoke, last-used), deployments (publish an agent version,
  version pinning, rollback), a versioned run endpoint with streaming and idempotency keys,
  per-key rate limits.
- 6D Approval notifications and the separation-of-duties setting (3.6).
- 6E Minimal evaluations: datasets and cases, assertions on output, structured output and tool
  calls, a prompt-injection suite, cost and latency per case, run against a specific version.
  LLM-as-judge only with its limitations stated on screen.
- Accept when: a published agent can be called with an API key, a signed webhook, and a schedule,
  each producing exactly one run per event, and evals run against two versions.

### Phase 7: memory and knowledge
- pgvector with a retrieval interface so another vector store can be added later.
- Document ingestion (safe file handling, size and type limits, path-traversal protection),
  chunking, embeddings through the provider abstraction, hybrid (vector plus keyword) search,
  metadata filters, source citations.
- Memory scopes: run, agent, organization. Explicit write only; nothing is stored automatically.
  Inspect, edit, export, delete. Retention policy (3.9).
- Retrieved text goes through the untrusted-output wrapper (3.8).
- Accept when: an agent answers from uploaded documents with citations, memory never crosses
  organizations or agents (RLS test), and deletion really removes chunks and embeddings.

### Phase 8: workflows and multi-agent
- 8A Workflow definition as validated JSON (Pydantic), versioned, with graph validation: no
  cycles outside bounded loops, every node reachable, schemas compatible, hard iteration caps.
- 8B Executor for the node set in section 2, one step row per node, pause and resume reusing the
  approval and checkpoint machinery.
- 8C React Flow editor: drag and drop, connect, configure, validate, node status and errors,
  autosave, undo and redo, import and export, run with a sample input, inspect node input and output.
- 8D Multi-agent as agent-as-tool handoffs and supervisor and worker patterns, parallel branches,
  shared budget pool, depth and handoff limits, structured messages, context passed explicitly.
- Accept when: a supervisor workflow with two workers and one approval gate runs, pauses, resumes,
  respects every budget, and cannot recurse.

### Phase 9: ecosystem, hardening and launch
- OpenAPI tool import and an MCP client behind a permissioned adapter; GitHub, Gmail and Google
  Calendar tools as separate, individually risk-classified tools.
- SDKs generated from OpenAPI (Python, TypeScript) and a thin CLI (`init`, `agents list|run`,
  `workflows validate|run`, `test`, `deploy`, `logs`). Each command tested and documented.
- Locust load tests against the Compose stack; document hardware, workload, configuration and
  measured results only. Never state numbers that were not measured.
- Security review against section 5, backup and restore drill, graceful shutdown, readiness and
  liveness checks, production deployment (Render, Vercel, Supabase), self-hosting guide.
- Open-source files: LICENSE (Apache-2.0 after dependency review), CONTRIBUTING, SECURITY,
  CODE_OF_CONDUCT, issue and PR templates, ROADMAP, CHANGELOG.

### After launch (not in scope until asked)
Billing (Stripe, M-Pesa), marketplace, code-execution sandbox, more providers (Anthropic,
OpenAI-compatible, Ollama), multi-environment deployments, projects.

---

## 5. Security rules (apply to every phase)

- Treat documents, web pages, emails, tool output, retrieved knowledge and user prompts as
  untrusted. Policies and permissions never come from them.
- Validate every external input. Model-chosen tool arguments are validated against the schema
  before any handler sees them.
- Every sensitive tool needs approval; the switch cannot be turned off for it.
- Network tools: https only, admin-listed hosts, resolved addresses must be public, no redirects
  to unlisted hosts, size and time limits (see `docs/http-tools.md`).
- Secrets are write-only, redacted in logs, runs, audit and errors. Never in `config`.
- Backend authorization on every route; database RLS as the second layer. Cross-tenant access
  attempts return 404.
- Anything granted because of an email address uses `ConfirmedUser`.
- Inbound webhooks: signature, timestamp tolerance, replay and duplicate protection.
- Uploads: size and type limits, safe storage names, no path traversal, no execution.
- Audit log every sensitive operation. No audit entry may contain a secret or a note body.

---

## 6. Engineering rules

1. Inspect before changing. Preserve my work. Never overwrite a file you have not read.
2. Ask before destructive operations (deleting files, dropping data, rewriting history).
3. Every model change has an Alembic migration that goes up, down and up again, and
   `alembic check` passes.
4. Tests for what you build, including the security and concurrency cases named in each phase.
   Do not say a feature works until its tests have actually run, and report the real results.
5. No fake data, fake metrics or buttons that do nothing.
6. Config through environment variables only. Never commit `.env` or a secret.
7. No unlimited loops or autonomous recursion. Every run has bounded steps, time, tokens, cost.
8. Treat background jobs as at-least-once. Side effects need idempotency.
9. Keep routers -> services -> repositories, strict mypy, ruff, ESLint and Prettier clean.
10. Avoid new dependencies unless they clearly reduce risk or work. Name any you add.
11. Document decisions in `docs/`. Update `CLAUDE.md` phase status. State limitations honestly.
12. If a requirement is ambiguous, make a reasonable decision, record it, and tell me. Ask only
    when the answer genuinely changes the design.

---

## 7. How to work with me

I develop on Windows with VS Code and PowerShell, in Docker Desktop. Use Windows-safe commands.

Before each phase: write a short design note (`docs/phaseN-design.md`) with decisions, risks,
data model changes and the step breakdown, and wait for my approval.

Deliver each step as:
- the full contents of every changed file (not snippets), packaged as a zip of the changed files;
- an explicit list of deleted or moved files, because a zip cannot delete anything;
- one PowerShell block that I can run top to bottom: `cd` into the repo, `git rm` deleted files,
  `Expand-Archive` the zip, `docker compose up -d --build`, migration and test checks,
  `git add`, `git commit`, `git pull --rebase origin main`, `git push origin main`.

At the end of every step report: what was implemented, files changed, dependencies added,
database changes, tests run with actual results, known limitations, how to try it by hand, and
the next step. Keep reports short.

Do not attempt several steps in one go. Do not stop at planning once a design is approved.

---

## 8. Final acceptance (all must be true before 1.0)

Register and create an organization; create and configure agents; run them with Gemini; set tool
permissions; require approvals; see live run events; pause, resume and cancel; schedule runs and
trigger them by signed webhook or API key; publish, pin and roll back versions; evaluate versions;
use knowledge and memory with citations; build and run a workflow with multiple agents; stay inside
quotas under concurrent load; recover from a killed worker; keep every organization's data
isolated; self-host with Docker Compose; use the generated SDKs and the CLI; read accurate
documentation; and contribute through the open-source process.
