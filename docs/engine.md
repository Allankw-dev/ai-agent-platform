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
2. the tool needs a person's approval (sensitive tools always do): **approvals are Phase 4, so
   for now such a call is skipped and the model is told it was not run**;
3. there is no handler for it yet;
4. the arguments do not match the tool's JSON schema (`jsonschema`);
5. the handler runs longer than the tool's timeout, or raises. The model and the user only see a
   generic message; details go to the logs.

## Limits

An agent version has `max_iterations`, `timeout_seconds`, `max_total_tokens` and an optional
`cost_budget_usd`, each capped by the platform ceilings (`AGENT_*_CEILING`). The ceilings are
applied again when a run starts, so lowering one also constrains older versions.

- Iterations, tokens and cost are checked **before each model call**, so a run can overshoot a
  token or cost limit by at most one call.
- The timeout wraps the whole run, including a model call that hangs.
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

## Lifecycle and failure handling

- Starting a run is refused up front (503 `ai_not_configured`) if the agent's provider has no key.
- If the hand-off to Celery fails, the run is marked failed and its idempotency key is freed, so
  the caller can retry (503 `queue_unavailable`).
- `Idempotency-Key` header: the same key returns the original run (200) instead of starting
  another. A key belongs to one agent.
- A task is acknowledged late and may be redelivered after a worker crash. A run found already
  `running` on redelivery is marked failed ("interrupted"), never run twice. Finished runs are
  skipped.
- A worker acts for an organization, not a user: it sets only `app.org_id`, so Row Level Security
  still isolates tenants. Asking for a run with the wrong organization finds nothing.

## Not yet

- Approvals (Phase 4): sensitive tools are skipped, not paused.
- Conversation memory: `memory_config` is stored on versions but runs are single-turn.
- Streaming output, retries of failed runs, schedules and webhooks.
