# Phase 5 design: run reliability and quotas

Status: **approved** (all eight decisions accepted as recommended). 5A, 5B and 5C are built and
tested; 5D and 5E are not started.

Changes made while building 5B, all small:

- Developers can **read** the limits and usage (they start the runs that use the quota, and a
  refused run quotes the numbers anyway). Only owners and admins change them. The design said only
  owners and admins could read them.
- Two refusals the design did not name: `409 run_exceeds_daily_quota` (the agent's own budget is
  bigger than the whole quota, so waiting cannot help) and `409 cost_quota_needs_price`.
- The provider limiter's per-minute setting is `PROVIDER_CALLS_PER_MINUTE` (the design said
  `PROVIDER_RPM`), and a slot is held through the Gemini client's own retries.
- `DELETE /limits` resets an organization to the platform defaults.

Changes made while building 5C:

- **Idempotency was added to the scope** (at your request). Every tool call has a call key that is
  unique per run in the database, so a call starts at most once however often a task is delivered
  and a finished call is *replayed* from its recorded result instead of run again. Tools receive a
  stable `idempotency_key` and `http.request` sends it as an `Idempotency-Key` header on writes.
  This also makes recovery safe for approved actions that had *finished* before the crash, which the
  design could only fail. An approved action that had *started* is still never retried.
- The heartbeat lives in the database (`agent_runs.heartbeat_at`) as well as in Redis; the database
  decides, Redis only lets the scheduler find candidates (decision 5, unchanged).
- A task delivered twice for a *running* run no longer fails it: it is ignored if the worker is
  alive and takes the run over if it is not. Before, a duplicate delivery ended a live run.
- Resuming after an approval now keeps the saved state (as progress) instead of clearing it, noting
  only which approval it answers, so a worker lost right after claiming a resumed run is replaceable.
- `RUN_MAX_ATTEMPTS` counts the first attempt (3 means two recoveries), and each attempt has the
  agent's full time limit.

Goal: before schedules, webhooks and API keys can start runs with nobody watching (Phase 6), runs
must be observable live, bounded by quotas, and recoverable after a worker dies.

Steps: 5A event log and streaming, 5B limits and quotas, 5C crash recovery, 5D observability and
audit, 5E emergency stop. Each step leaves the app running and tested.

---

## 5A. Run event log and streaming

### Data
New table `run_events` (tenant table, RLS like the others):

| Column | Notes |
| --- | --- |
| `id`, `org_id` | standard; `(run_id, org_id)` composite foreign key to `agent_runs` |
| `run_id`, `seq` | `seq` starts at 1 per run; `UNIQUE (run_id, seq)` |
| `type` | see below |
| `data` | small JSON: ids, statuses, token counts. **Never** tool arguments, tool output or message text |
| `created_at` | |

New column `agent_runs.event_seq` (counter). An event is written with
`UPDATE agent_runs SET event_seq = event_seq + 1 ... RETURNING event_seq` and the insert in the
same transaction, so sequence numbers are gap-free per run and safe with two writers (a worker and
an API request cancelling at once).

The runtime role may INSERT and SELECT `run_events`, never UPDATE or DELETE (like `audit_logs`).

Event types: `run.queued`, `run.started`, `step.started`, `step.finished`,
`approval.requested`, `approval.decided`, `run.awaiting_approval`, `run.resumed`, `run.finished`
(with final status), `run.cancelled`. Phase 5C adds `run.recovered`.

Events say *that something changed*. The client fetches the details with the existing
`GET /runs/{id}`. This keeps one source of truth and means events can never leak a secret.

### Emission
One helper, `repositories/run_events.emit(session, run_id, type, data)`, called from the recorder
(steps, usage), the executor (claim, pause, resume, close), the run service (create, cancel) and
the approval service (decide, expire). Tests assert the exact event sequence of a plain run, a
cancelled run, an approved run, a rejected run and an expired approval.

### Endpoint
`GET /organizations/{org}/runs/{run}/events/stream?after=<seq>` (also accepts `Last-Event-ID`).
Server-sent events, each frame `id: <seq>`.

- **Auth:** browsers' `EventSource` cannot send an `Authorization` header and putting a token in
  the URL leaks it into logs. The frontend uses `fetch` with a streaming body and parses the
  frames itself. No new token type.
- **No held connections:** the route authorizes, then releases its database session before
  streaming (FastAPI would otherwise keep it until the stream ends and exhaust the pool). Each
  poll opens a short transaction through the sessionmaker with `use_tenant`.
- **Loop:** every 1 second read events with `seq > last` (indexed, limit 100); a comment frame
  every 15 seconds as a heartbeat; close once the run is finished and all events are sent;
  close after 5 minutes so clients reconnect with `after=<last seq>`.
- **Replay:** `GET /runs/{id}/events?after=&limit=` returns the same events as JSON.

### Frontend
The run page opens the stream and re-fetches the run when an event arrives. If the stream fails,
it falls back to the current polling. Reconnects use the last seen `seq`.

---

## 5B. Limits, quotas and usage

### Per-run limit: `max_tool_calls`
Added to `Limits` (default 20, platform ceiling `AGENT_MAX_TOOL_CALLS_CEILING`, default 100). It
lives in the version's `limits` JSON, so no migration: old versions read the default. The engine
counts tool calls (attempted, including failed ones) and stops the run with a clear message when
the limit is reached. The count is saved in checkpoints (read with a default of 0, so runs paused
before this change still resume). Shown in the agent form and configuration summary.

### Organization limits
New table `org_limits` (one optional row per organization; absent means platform defaults from
settings `ORG_DEFAULT_*`):

| Limit | Default |
| --- | --- |
| `max_concurrent_runs` (queued + running) | 5 |
| `daily_token_quota` (UTC day) | 500,000 |
| `daily_cost_quota_usd` | none |

Only owners and admins can read and change them (`GET` and `PUT /organizations/{org}/limits`).
The same table gets `runs_paused` fields in 5E.

### Atomic reservation (no new reservation table)
`agent_runs` gets `reserved_tokens` and `reserved_cost_micro`. When a run is created, in the same
transaction, under `pg_advisory_xact_lock(hash(org_id))`:

1. Count runs in `queued` or `running`: refuse if at `max_concurrent_runs`.
2. Tokens still reserved = sum over open runs (`queued`, `running`, `awaiting_approval`) of
   `max(reserved_tokens - tokens already used, 0)`. Add tokens used today from `usage_records`.
   Refuse if adding this run's reservation (the version's effective `max_total_tokens`) would
   exceed the daily quota. Same for cost when a cost quota is set.
3. Store the reservation on the new run.

Because the reservation lives on the run and only open runs count, **a run that ends in any way
(success, failure, cancel, expiry, orphan cleanup) releases its reservation automatically**. There
is no settle step that a missed code path could forget, which is the usual way reservations leak.
An idempotent retry returns the original run before any quota check.

Refusals are `429` with codes `concurrency_limit_reached` and `daily_quota_reached` and a plain
message (with the reset time for the daily quota). The run form shows them as they are.

Pessimistic by design: reserving the version's full token budget means 500,000 tokens allows ten
default-sized runs at once. Admins can raise the quota.

### Provider limiter (Gemini free tier)
A Redis limiter in front of every model call, as one Lua script so it is atomic across workers:
at most `PROVIDER_MAX_CONCURRENT_CALLS` calls in flight (default `{"gemini": 4}`), and an optional
requests-per-minute window `PROVIDER_RPM` (default unset). In-flight entries are leases that expire
after the call timeout, so a dead worker cannot hold a slot forever. A call waits briefly for a slot
(waiting counts against the run's time limit) and otherwise fails with a clear message. A 429
response honours `Retry-After`. If Redis errors, the call proceeds and a warning is logged: the
limiter protects the provider quota, it is not a security control.

### Usage page
`GET /organizations/{org}/usage` returns today's totals and the last 30 days by day and by agent,
from `usage_records`. A Usage tab shows it next to the limits form. Real data only; an empty state
when there is none.

---

## 5C. Crash recovery

### What exists
A worker crash today ends in a failed run: "interrupted" on redelivery, or the orphan check after
the timeout ceiling plus three minutes (up to about eight minutes).

### Heartbeat and discovery
- While a run executes, its worker updates a Redis sorted set `runs:active` every 15 seconds
  (member `org_id:run_id`, score = time) and removes the entry when the run ends.
- A new Celery beat service (`scheduler` in Compose) runs `agents.recover_stale_runs` every 30
  seconds. It reads members with a score older than 60 seconds from Redis, then handles each run in
  the database under that organization's tenant context.
- This is deliberate: row level security stops any query from seeing other organizations' runs, and
  Redis gives workers a way to *find* candidates without weakening that. Redis only discovers; the
  database decides. If Redis is lost, the existing read-time orphan check still works.

### Fencing
`agent_runs.attempt` starts at 1. Recovery claims a stale run with one atomic update and increments
`attempt`. A worker's writes (heartbeat, step records, close) are conditional on its own attempt, so
a worker that was only stalled and wakes up after recovery stops quietly instead of running the same
run twice.

### Progress checkpoints
After each model call and after each batch of tool results, the engine saves the loop's state on
the run (the same checkpoint format as approvals, plus `kind: "progress"`). One JSON write per
iteration, at most 25 per run.

### What recovery may do
| The worker died during | Recovery |
| --- | --- |
| a model call | Run the model call again from the checkpoint. No side effect happened. |
| a tool that is not sensitive | Close that step as failed ("interrupted"), run it again from the checkpoint. Rule: a non-sensitive tool must be read-only (added to `CLAUDE.md`). |
| a sensitive tool (HTTP write, Slack) | **Never retried.** The run fails saying it is unknown whether the action happened (existing behaviour). |
| anything, with no checkpoint | Fail with "interrupted". |

At most 3 attempts per run, so a run that kills its worker cannot loop forever. Each recovery
writes a `run.recovered` event and an audit entry, and the run page says so.

### Not in this phase
Per-tool retry policies. Models already see tool errors and retry on their own, and nothing needs
more yet. Revisit in Phase 6 when triggers call external APIs.

---

## 5D. Observability and audit

- **Sentry** (the `SENTRY_DSN` setting exists, nothing uses it): FastAPI and Celery integrations,
  `send_default_pii=False`, a `before_send` hook that applies the existing redaction rules.
- **OpenTelemetry**: instrument FastAPI, SQLAlchemy, httpx and Celery. Trace context travels from
  the API request into the Celery task, so one run is one trace. Custom spans for each model call
  and tool call with **only** ids, tool key, status and token counts as attributes: never prompts,
  arguments, outputs or secrets. Export over OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set,
  otherwise nothing is exported. A Jaeger service under a Compose profile (`observability`) lets you
  look at traces locally.
- **Audit coverage**: list every route that changes data, compare with the `audit.record` calls,
  and add what is missing. A test fails when a mutating route has no audit call or an explicit
  exemption.

---

## 5E. Emergency stop

New fields on `org_limits`: `runs_paused_at`, `runs_paused_by_id`. Owners and admins can **Stop
all runs** (with a confirmation dialog) and **Resume**.

While stopped:
- Creating a run is refused (`409 org_runs_stopped`).
- Open runs (queued, running, awaiting approval) are cancelled, with their approvals.
- A worker claiming a queued or resumed run for a stopped organization cancels it instead.
- Approving still records the decision but the run is not resumed.

Disabling an integration already takes effect on the next tool call, because the engine reads it
when the tool runs. That covers "disable a tool instantly" for provider tools. Audited.

---

## Migrations

- `0011`: `run_events`, `agent_runs.event_seq`, `org_limits`, `agent_runs.reserved_tokens`,
  `reserved_cost_micro`; RLS and grants; downgrade tested.
- `0012`: `agent_runs.attempt`.
- Every migration goes up, down, up, and `alembic check` passes. RLS tests cover the new tables.

## Tests (named in advance)

- Events: exact sequence for plain, cancelled, approved, rejected and expired runs; two writers
  never produce a duplicate or a gap; no secret appears in any event; stream resumes from `after`.
- Quotas: N simultaneous create requests against a limit of M create exactly M; an idempotent retry
  is not counted twice; a cancelled, failed or expired run frees its reservation; quota counts one
  organization only.
- Tool calls: the limit stops the run; a checkpoint from before this change still resumes.
- Provider limiter: concurrency never exceeded across parallel callers; a dead holder's slot
  expires; Redis down does not block a call.
- Recovery: a run killed mid-model-call resumes and finishes; killed mid read-only tool resumes;
  killed mid sensitive tool is never retried; a stalled worker that wakes up after recovery stops;
  the third crash fails the run.
- Emergency stop: creation refused, open runs cancelled, approval does not resume.
- Frontend: run page applies stream events, reconnects with the last seq, falls back to polling;
  limits form validation; quota error messages; usage empty state.

## Risks

- **Missed emission points** leave the run page stale. Mitigated by the sequence tests and the
  polling fallback.
- **The advisory lock serializes run creation per organization.** Acceptable at this scale; it is
  held for a few milliseconds.
- **Recovery is the hardest part.** If 5C proves bigger than expected, split it: detection and
  fencing first, resume logic second.
- **Progress checkpoints add a write per iteration.** Small, and measured in Phase 9, not assumed.

## Decisions to confirm

1. Event payloads carry only ids and statuses; details come from `GET /runs/{id}`. **Recommended.**
2. Streaming uses `fetch` with the bearer token, not `EventSource`. **Recommended.**
3. Reservations live on `agent_runs`, no separate table. **Recommended.**
4. Defaults: 5 concurrent runs, 500,000 tokens per day, no cost quota, 20 tool calls per run (ceiling
   100), Gemini concurrency 4.
5. Redis discovers stale runs, the database decides (not cross-organization SQL). **Recommended.**
   The alternative is a database role that bypasses row level security for maintenance tasks. It
   would also help Phase 6 schedules, but I have not verified that hosted Supabase allows creating
   such a role, so I would not build on it without checking.
6. Delegation depth is **not** added now. It arrives with the multi-agent migration in Phase 8
   instead of a field that nothing uses for three phases.
7. Per-tool retry policies are deferred (see 5C).
8. Emergency stop cancels open runs rather than pausing them for later.
