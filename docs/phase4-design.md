# Phase 4 design: credentials, real tools and approvals

**Status: proposed, waiting for review. No code has been written.** Section 0 lists the decisions
that need an answer; my recommendation is in bold. Say "accept all" or change any of them.

## 0. Decisions

| # | Question | Recommendation | Other option |
| --- | --- | --- | --- |
| 1 | Who may approve or reject an action? | **Owners and admins** | Also developers |
| 2 | May a person approve a run they started themselves? | **Yes for now** (small teams); a per-organization "needs a different person" switch comes later | Never |
| 3 | How long does an approval stay open? | **24 hours**, then it expires and the run fails | Shorter or configurable |
| 4 | HTTP tool: which sites may an agent call? | **Only hosts an admin has listed** for that integration (empty list means none) | Any public site |
| 5 | Slack sign-in method | **A bot token pasted by an admin** (simple, safe, enough for the MVP) | A full "Add to Slack" OAuth flow later |
| 6 | How a paused run is stored | **Our own checkpoint saved on the run** (the loop is small and its state is already plain JSON) | LangGraph's Postgres checkpointer (new dependency, more moving parts) |
| 7 | HTTP tools | **Two tools:** `http.get` (read-only, runs freely) and `http.request` (any method, always needs approval) | One tool for everything |

## 1. Goals and non-goals

**Goals:** agents can use real services (any allowed website over HTTP, and Slack); a sensitive
action never runs until a person has seen exactly what it will do and approved it; secrets are
stored encrypted and never leave the server; every credential and approval event is audited.

**Not in Phase 4:** OAuth "connect" flows, GitHub, Gmail and Calendar tools, approval
notifications by email or Slack, per-organization approval policies, a key-rotation screen, a
separate database role just for secrets, workflows and schedules. They reuse this design later.

## 2. What already exists (reused, not rebuilt)

- Tables: `integrations` (connected accounts, non-secret config), `credentials` (encrypted payload
  and `key_version`), `approvals` (proposed input, status, expiry, who decided, note),
  `audit_logs`; all with Row Level Security.
- The tool catalog marks each tool with a `provider` and `is_sensitive`; an agent's tool grant has
  `requires_approval` and a free `config`.
- Run status `awaiting_approval` exists. Today the engine fails closed: a tool that needs approval is
  skipped and the model is told so. Phase 4 replaces that skip with a pause.
- Settings: `CREDENTIAL_ENCRYPTION_KEY` is already declared.

## 3. Credential vault (4A)

- **Encryption:** AES-256-GCM (the `cryptography` library). The key is 32 random bytes in
  `CREDENTIAL_ENCRYPTION_KEY`, never in git. The stored value is nonce plus ciphertext, tagged with
  `key_version` so a new key can be introduced later. The organization and integration ids are bound
  into the encryption, so a ciphertext copied to another row or organization cannot be decrypted.
- **Who:** owners and admins add, replace or delete a secret. Developers can use an integration in an
  agent but cannot see or change its secret. Nobody can read a secret back: the API only says
  "a credential is saved, by whom, when".
- **Where it is decrypted:** one module reads the encrypted column, and only inside the worker at the
  moment a tool call runs. The plain value is never logged, never stored in a run step, never sent to
  the model, and is redacted if a tool's output happens to contain it. Log output filters fields named
  like `token`, `secret`, `authorization` and `password`.
- **No key set:** the platform starts normally but refuses to save or use credentials, with a clear
  message.
- **Tests:** round trip; wrong key; tampered data; ciphertext moved to another row or organization;
  no endpoint, log line or run step ever contains a secret; members and developers get 403;
  another organization gets 404; every change appears in the audit log without the secret.

## 4. Tools

**How a tool gets its integration.** The agent's tool grant carries `integration_id` in its `config`.
Saving a version checks that the integration belongs to the organization, matches the tool's
provider and is active.

### 4.1 HTTP tools (4B): `http.get` and `http.request`

| Control | Rule |
| --- | --- |
| Allowed hosts | Exact host names listed on the integration. An empty list refuses every request. |
| Scheme | `https` only. |
| Address check (SSRF) | The host is resolved and **every** address must be public. Refused: loopback, private ranges, link-local (including the cloud metadata address 169.254.169.254), shared/CGNAT, multicast, unspecified, IPv6 local ranges and IPv4-mapped IPv6. The check is applied to the address actually connected to, which stops DNS rebinding. Proxy settings from the environment are ignored. |
| Redirects | Not followed automatically. Up to 3 hops, each fully re-checked, and credentials are never sent to a different host. |
| Limits | 20 s timeout (never above the tool's own), request body up to 100 KB, response up to 1 MB (read as a stream and cut off). Only text and JSON come back; binary is refused. |
| Headers | The agent cannot set `Host`, `Authorization`, `Cookie` or connection headers. The integration's credential adds its own auth header. |
| Output | Returned as untrusted data: it is content to read, never instructions to follow. |

`http.get` is read-only and runs without approval. `http.request` (POST, PUT, PATCH, DELETE) is
sensitive and always needs approval.

### 4.2 Slack (4C): `slack.send_message`

- Sensitive, so it always needs approval.
- The integration holds the bot token and `allowed_channels` (channel ids). A message to any other
  channel is refused before anything is sent.
- Fixed host (`slack.com`), text up to 3,000 characters, link previews off, and `@channel`, `@here`
  and `@everyone` are neutralised so an agent cannot ping a whole workspace.
- The approver sees the exact final text. Slack's errors are returned in a safe, short form.
- Setup you will do once: create a small Slack app in a throwaway workspace, give it the `chat:write`
  permission, install it, invite it to one test channel, and paste its bot token into the app.

## 5. Approvals (4D backend, 4E screens)

### 5.1 Flow

1. The model asks for a tool that needs approval. The engine validates the arguments exactly as it
   does today, then records an `approvals` row (pending) with the **validated arguments**, the tool,
   the model's stated reason and an expiry time.
2. The engine saves a checkpoint on the run (see 5.2), sets the run to `awaiting_approval` and the
   task ends. **No worker is held while people decide.**
3. An approver opens the inbox and approves or rejects, with an optional note. The decision is one
   atomic database update that only succeeds if the approval is still pending and not expired, so a
   double click or two people at once cannot decide twice.
4. A new task (`agents.resume_run`) claims the run (`awaiting_approval` to `running`, atomically) and
   continues from the checkpoint. **Approved:** the stored arguments are executed exactly as shown,
   never re-requested from the model. **Rejected:** the model is told "a person rejected this action"
   with the note, and decides how to finish.
5. Several tool calls in one reply are handled in order; the run pauses at each one that needs a
   person.

### 5.2 What is saved at a pause

A new `agent_runs.checkpoint` JSON column holds the conversation so far (the model's replies are kept
verbatim, which Gemini requires), the counters, the tool calls still to run, and the results already
collected. Iterations, tokens and cost keep adding up across pauses. The time limit applies to each
stretch of work, and waiting time is not counted.

### 5.3 Rules

| Situation | Behavior |
| --- | --- |
| Who decides | The `approvals:decide` permission (decision 1). The agent can never decide: the API needs a signed-in person. |
| Expiry | Pending approvals past their expiry become `expired` and the run fails with a clear message. This happens when approvals or runs are read and when someone tries to decide, like the existing clean-up of orphaned runs. |
| Cancelling a run | Cancels its pending approvals. A cancelled or finished run cannot be approved (409). |
| **At most once** | Before an approved action runs, its step is marked started. If the worker dies after that, the run fails with "it is unknown whether the action happened". **A sensitive action is never retried automatically.** |
| Repeated or late resume tasks | Harmless: only one resume can claim the run. |
| What the approver sees | Agent and version, tool, the exact arguments as they will run, the model's stated reason, a link to the run, and the time left. |
| Audit | `approval.requested`, `approved`, `rejected`, `expired`, plus the credential and integration events. |

### 5.4 API (new)

- `GET /organizations/{org}/integrations`, `POST`, `PATCH /{id}`, `PUT /{id}/credential`, `DELETE /{id}`
- `GET /organizations/{org}/approvals?status=pending`, `GET /{id}`, `POST /{id}/approve`, `POST /{id}/reject`
- The run detail gains its pending approval, so the run page can show it.

### 5.5 Database changes (one migration, 0006)

`agent_runs.checkpoint` (JSON), a new step status `awaiting_approval`, and indexes for the approvals
inbox. Everything else already exists.

### 5.6 Screens

An **Integrations** tab (list, add, replace secret, disable, delete; secrets are write-only);
an **Approvals** tab with a count of pending items; approve and reject buttons with a note on each
approval; the run page showing "Waiting for approval" with a link; and the agent form letting you
choose an integration for a tool.

## 6. Security checklist (all verified before Phase 4 is called done)

- No secret appears in any API response, log line, run step, error message or model input.
- The address check blocks every internal range, including the metadata address and rebinding tricks.
- Redirects, oversized responses and slow servers are handled, not followed or waited on.
- Tool output cannot trigger an action: sensitive actions always reach a person first.
- Tenants cannot see each other's integrations, credentials or approvals, tested at the database level.
- An action approved twice, or whose worker dies, still happens at most once.
- Members and developers cannot approve (decision 1), and cannot read or change secrets.

**A privacy point for you:** while Gemini is on the free tier, anything an agent reads or writes can
be used by Google to improve its products. Use fake or public data for these tests, and connect only a
throwaway Slack workspace. Real company data needs the paid tier.

## 7. Build order

Each step ships on its own, with tests, one zip and the usual command block, and waits for your
check before the next.

| Step | What | Main tests |
| --- | --- | --- |
| 4A | Credential vault, integrations API and screen | Encryption, no-leak, roles, tenant isolation, audit |
| 4B | Address check, `http.get`, `http.request`, integration choice on the agent form | Every blocked address class, redirects, limits, allowlist |
| 4C | `slack.send_message` | Channel allowlist, mention neutralising, mocked Slack |
| 4D | Pause and resume, approvals API, expiry, migration 0006 | Double decide, expiry, cancel, at-most-once, resume races |
| 4E | Approvals tab and run page states | Roles, decisions, empty and error states |
| 4F | End-to-end acceptance on your machine | Approve, reject and expire, with a real Slack message |

## 8. What I need from you

1. The seven decisions in section 0.
2. A throwaway Slack workspace (before 4C).
3. An encryption key (before 4A ships); I will give you the one-line command that creates it.

## 9. Risks and open points

- **Pause design (decision 6):** our own checkpoint is simpler and fully testable, but it is ours to
  maintain. LangGraph's checkpointer would add a dependency and a second place where state lives.
- **Queue delivery:** Redis can redeliver a task after a crash. The claim-then-run design makes that
  safe, and the at-most-once rule covers the dangerous case.
- **Credential reads share the runtime database role** in this phase. The discipline is in code and
  tests; a separate role for secrets is a later hardening step.
- **Approval fatigue:** if everything needs approval, people stop reading. Only sensitive tools do by
  default, and `requires_approval` stays a per-agent choice.
