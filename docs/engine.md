# The agent engine and runs

A **run** is one execution of an agent's current version against one message. The API queues it,
a Celery worker executes it, and every step is recorded as it happens.

```
POST /organizations/{org}/agents/{agent}/runs   -> run (status queued), handed to Celery
worker: agents.execute_run(run_id, org_id)
  claim (queued -> running) -> load version + tools -> loop -> close (succeeded | failed)
```

## The loop (`app/engine/graph.py`, LangGraph)

1. **call_model**: checks limits first, then asks the provider for the next move.
2. If the model asked for tools, **run_tools** executes them one at a time, feeds the results back,
   and returns to step 1. Otherwise the reply is the run's output.

Every model call and tool call is a row in `run_steps` (type, status, input, output, error,
tokens), written and committed as it happens, so a run can be watched live. Each model call also
adds a `usage_records` row and updates the run's token and cost totals.

## What is checked before a tool runs

Model-chosen tool calls are never trusted. In order, a call is turned into an error result for the
model (never an action) if:

1. the tool is not one this agent version was given (including names the model invented);
2. there is no handler for it yet;
3. the arguments do not match the tool's JSON schema (`jsonschema`);
4. the handler runs longer than the tool's timeout, or raises. The model and the user only see a
   generic message; details go to the logs.

Only after checks 1 to 3 pass does the engine consider approval: a tool that needs a person's
approval (sensitive tools always do) **pauses the run** instead of running. See `docs/approvals.md`.

## Limits

An agent version has `max_iterations`, `max_tool_calls`, `timeout_seconds`, `max_total_tokens` and
an optional `cost_budget_usd`, each capped by the platform ceilings (`AGENT_*_CEILING`). The
ceilings are applied again when a run starts, so lowering one also constrains older versions. These
are limits of one run; limits of a whole organization are in "Organization limits and quotas" below.

- Iterations, tokens and cost are checked **before each model call**, so a run can overshoot a
  token or cost limit by at most one call.
- **Tool calls** (`max_tool_calls`, default 20, ceiling 100) are counted when each call starts, and
  every attempt counts, failed ones too. A reply that asks for more calls than remain runs the ones
  that fit and then stops. A call that waited for approval counts once, not again when it resumes.
  The count is saved in checkpoints (older checkpoints without it read as 0). Versions saved before
  this limit existed read the default.
- After a tool's arguments pass its schema, an optional per-tool *preparer* turns them into their final
  form (for Slack, the message text made inert) before the tool runs; see `docs/slack-tool.md`.
- **Pause and resume.** When an action needs approval the graph ends early; the executor saves the
  loop's state as a checkpoint on the run and sets it `awaiting_approval`. `resume_run` (Celery task
  `agents.resume_run`) claims the run once the approval is decided, restarts the graph at the tools
  node with the decision, and continues. Repeated or late resume tasks are harmless. The time limit
  and orphan check count from the last resume.
- Each tool call gets a context with the run's ids, how to reach the organization's integrations
  (`integrations`) and the settings of that agent's grant of the tool (`tool_config`).
- The timeout wraps the whole run, including a model call that hangs. A run that fails mid-step (the
  time limit, a crash, an interrupted redelivery) also closes that step as failed, so no step is
  left showing "running" on a finished run.
- Cancelling a run (`POST .../runs/{id}/cancel`) is noticed before the next model call.

A run that stops on a limit is `failed` with a message saying which limit, and keeps the last text
the model produced in `output`.

## Cost estimates

Token counts come from the provider (for Gemini, thinking tokens count as output, as they are
billed). Dollar costs are **estimates** from the `MODEL_PRICES` setting. There is no built-in
price list because prices and model names change often. Example (replace each `<USD>` with the price per
million tokens from the provider's pricing page):

```
MODEL_PRICES={"gemini-3.5-flash": {"input_per_mtok": "<USD>", "output_per_mtok": "<USD>"}}
```

A model with no price costs 0. An agent that has a `cost_budget_usd` is **refused** (the run
fails immediately) for a model with no price, rather than silently never hitting its budget.

## Providers

`app/engine/llm.py` defines the neutral message format and the `LLMClient` interface. Gemini is
implemented (`app/engine/gemini.py`, REST over httpx). Adding a provider means writing one client
and registering it in `get_llm_client`; the engine does not change.

Gemini notes:

- Each assistant turn's raw `parts` are stored as `provider_state` and sent back unchanged.
  Gemini 3 and newer reject tool-calling history without the "thought signatures" they issued.
- Tool schemas are reduced to the OpenAPI subset Gemini accepts; stricter keywords such as
  `additionalProperties` are still enforced by our own validation.
- 429 and 5xx responses are retried twice (2 s, then 6 s). The **free tier has strict per-minute
  limits**; a run that hits them fails with a clear message. Free-tier prompts may be used by
  Google to improve its products (`GEMINI_TIER=free`): use fake or public data only.

## In the app

- **Run an agent:** the agent's page has a "Run this agent" box (owners, admins and developers).
  Starting a run opens its run page. Each attempt carries an `Idempotency-Key`, so a double click
  or a retry of the same message never starts two runs; editing the message makes a new key.
  Draft and active agents can run; a disabled agent says so instead of showing the box.
- **Run page** (`/orgs/{org}/runs/{id}`): the message, the answer or the error, tokens, an
  estimated cost, time taken, and a step-by-step timeline (every model call and tool call with
  its input, output and failure). It refreshes itself every 2 seconds until the run finishes.
  Managers can **Cancel** a running run or **Run again** a finished one.
- **Runs tab** (`/orgs/{org}/runs`): all runs, newest first, filterable by agent and status. It
  refreshes every 5 seconds while any listed run is still going.
- **Cost:** shown as "Not estimated" when tokens were used but the server has no price for the
  model (see Cost estimates), never as a misleading $0.
- **Roles:** everyone can open runs; only owners, admins and developers can start or cancel them.

## Troubleshooting model calls

A failed model call shows its reason in the run's `error` field and on the failed step:

| Message | Meaning | What to do |
| --- | --- | --- |
| `The model 'x' is overloaded right now (HTTP 503)` | Google has no capacity for that model. Common on free tiers, and it can take about a minute to say so. | Try again later or pick another model. |
| `The model 'x' did not answer within N seconds` | The model was too slow (`LLM_TIMEOUT_SECONDS`, default 60). | Same as above. |
| `The AI provider could not be reached` | The container cannot connect (network, proxy, VPN). | Check Docker's network access. |
| `... rate limiting requests` | Free-tier per-minute limit (HTTP 429). | Wait a minute. |
| `... does not know the model 'x'` | The name does not exist for your key. | Run `.\scripts\check-gemini-models.ps1`. |

An overloaded or slow model is not retried when its failure already took more than 15 seconds,
because retrying would only use up the run's time limit.

## Organization limits and quotas

A whole organization is also bounded (Phase 5B), so many runs at once, or a loop of runs started by
a script, cannot spend without limit. Owners and admins set the limits on the **Usage** tab
(`GET`/`PUT`/`DELETE /organizations/{org}/limits`); until they do, the platform defaults apply
(`ORG_DEFAULT_MAX_CONCURRENT_RUNS` 5, `ORG_DEFAULT_DAILY_TOKEN_QUOTA` 500,000,
`ORG_DEFAULT_DAILY_COST_QUOTA_USD` none).

| Limit | What it counts |
| --- | --- |
| Runs at once | Runs `queued` or `running`. A run waiting for a person holds no worker, so it does not count. |
| Tokens per day | Tokens used since midnight UTC, plus what open runs may still use. |
| Cost per day (optional) | The same, in estimated US dollars. |

**Reservation.** When a run is created it reserves its token limit (and its cost budget) in the same
transaction that inserts it, under a per-organization lock (`pg_advisory_xact_lock`), so twelve
requests arriving together against a limit of five let exactly five in. The reservation lives on the
run (`reserved_tokens`, `reserved_cost_usd`) and counts only while the run is open. There is no
"settle" step to forget: a run that succeeds, fails, is cancelled, expires or is cleaned up as an
orphan stops being open, and its reservation stops counting. While a run is open it holds its
reservation minus what it has already spent (spending is counted in the day's usage already, so
counting it again would make every long run look twice as expensive).

A refused start creates nothing and says why, in plain words:

| Status and code | Meaning |
| --- | --- |
| `429 concurrency_limit_reached` | Too many runs are queued or running. |
| `429 daily_quota_reached` | Used plus held plus this run would pass the daily quota. `Retry-After` is the seconds until midnight UTC. |
| `409 run_exceeds_daily_quota` | This agent's budget alone is bigger than the whole daily quota; waiting would not help. |
| `409 cost_quota_needs_price` | A cost quota is set but the agent has no cost budget and its model has no price in `MODEL_PRICES`, so its cost cannot be limited. |

Without a cost budget, a run reserves the worst case: its token limit at the model's dearest rate. A
repeated request with the same `Idempotency-Key` returns the original run before any of this is
checked, so a retry is never refused for a run that already exists.

`GET /organizations/{org}/usage?days=30` returns today against the quota, a series for the last
`days` days (empty days included), and the heaviest agents. Usage is the sum of `usage_records`,
which are written from real model responses.

**Provider limits.** Model providers' own quotas (Gemini's free tier especially) are small and
shared by every worker, so each model call first takes a slot from a limiter kept in Redis
(`app/engine/provider_limiter.py`): at most `PROVIDER_MAX_CONCURRENT_CALLS` calls in flight per
provider (default `{"gemini": 4}`) and optionally `PROVIDER_CALLS_PER_MINUTE`. A slot is a lease that
expires by itself, so a worker that dies mid-call cannot hold it forever. A call that finds the
provider full waits up to `PROVIDER_WAIT_SECONDS` (30; the wait counts against the run's time limit)
and then fails with "the provider is busy"; a slot is held through the Gemini client's own retries.
If Redis cannot be reached the call goes ahead and a warning is logged: the limiter protects the
provider's quota, it is not a security control.

## Run events and streaming

Besides its steps, every run keeps an append-only **event log** (`run_events`, Phase 5A): a short
record of each change, numbered `seq` 1, 2, 3 ... per run with no gaps.

| Event | When |
| --- | --- |
| `run.queued` | the run was created |
| `run.started` | a worker picked it up |
| `step.started`, `step.finished` | a model call or tool call began or ended (`data`: step id, type, tool key, status) |
| `approval.requested` | a risky action is waiting for a person |
| `run.awaiting_approval` | the run paused and released its worker |
| `approval.decided` | a person approved or rejected, or it expired or was cancelled (`data.decision`) |
| `run.resumed` | a worker carried on after the decision |
| `run.finished` | succeeded or failed (`data.status`) |
| `run.cancelled` | cancelled; always the last event of such a run |

Rules the code keeps:

- An event is written **in the same transaction** as the change it describes (`run_events.emit`
  from the repository or recorder that makes the change), so they commit together. A reader that
  sees a finished run is guaranteed to find its last event.
- The number comes from one atomic `UPDATE` of `agent_runs.event_seq`, so two writers (a worker and
  a person cancelling) never take the same number.
- `data` holds ids, statuses and counts **only**. Never tool arguments, tool output or message text:
  an event can never leak what a step handled. Clients fetch details with `GET /runs/{id}`.
- The log is append-only for the application's database role, like the audit log, and has Row Level
  Security like every tenant table.

Reading it:

- `GET /organizations/{org}/runs/{run}/events?after=<seq>&limit=` returns events as JSON (replay).
- `GET /organizations/{org}/runs/{run}/events/stream?after=<seq>` is a server-sent event stream.
  Each frame has `id: <seq>`, `event: <type>` and a JSON `data:` line. Keep-alive comments
  (`: keep-alive`) are sent while nothing happens. The stream ends when the run finishes, and after
  `RUN_STREAM_MAX_SECONDS` (300) otherwise: **reconnect with `after=<last seq seen>`** (or the
  standard `Last-Event-ID` header) and you receive only what you missed. The server looks for new
  events every `RUN_STREAM_POLL_SECONDS` (1) and keeps no database connection between looks.
- Browsers' `EventSource` cannot send an `Authorization` header, so the web app (and anything else)
  reads the stream with `fetch` and the same bearer token as any other call
  (`frontend/src/lib/run-events.ts`). The run page refreshes when an event arrives, checks only
  every 30 seconds while connected, and falls back to checking every 2 seconds if no stream can be
  opened. Try it from PowerShell with `scripts/watch-run.ps1`.

## Lifecycle and failure handling

- Starting a run is refused up front (503 `ai_not_configured`) if the agent's provider has no key.
- If the hand-off to Celery fails, the run is marked failed and its idempotency key is freed, so
  the caller can retry (503 `queue_unavailable`).
- `Idempotency-Key` header: the same key returns the original run (200) instead of starting
  another. A key belongs to one agent.
- A task is acknowledged late and may be redelivered after a worker crash. A run found already
  `running` on redelivery is marked failed ("interrupted"), never run twice. Finished runs are
  skipped.
- **Orphaned runs.** If a worker dies mid-run (Docker restarted, the machine slept), the run would
  say "running" forever. Whenever runs are read (the list or a single run), any run that has been
  "running" longer than the longest allowed run plus a 3 minute margin
  (`AGENT_TIMEOUT_CEILING_SECONDS` + 180 s) is marked failed, and its unfinished steps with it. A
  run still inside its time limit is never touched, and neither is a **queued** run: its task is
  still in the queue and will run when a worker returns. The run page says so when a queued run has
  waited over a minute.
- **Restarts.** The compose services use `restart: unless-stopped`, so Docker brings the worker
  (and everything else) back after an engine restart. A stopped worker with queued tasks was the
  cause of a run stuck on "queued" during development.
- A worker acts for an organization, not a user: it sets only `app.org_id`, so Row Level Security
  still isolates tenants. Asking for a run with the wrong organization finds nothing.

## Not yet

- Conversation memory: `memory_config` is stored on versions but runs are single-turn.
- Streaming of the model's text as it is written, retries of failed runs, schedules and webhooks.
