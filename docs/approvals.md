# Approvals

Some actions change things outside the platform (post a Slack message, send an HTTP write). An
agent can never do those on its own. The run **pauses**, a person sees exactly what would happen,
and only then does it run: **at most once, exactly as shown.**

Which tools need approval: every *sensitive* tool (`http.request`, `slack.send_message`), always,
and any other tool an agent version marks `requires_approval`. The switch cannot be turned off for
a sensitive tool.

## The flow

1. The model asks for a tool that needs approval. The engine checks the arguments as usual (bad
   arguments fail at once and nobody is asked), then records an approval holding the **final
   arguments** (for Slack, the cleaned text), the model's stated reason, and an expiry.
2. The loop's state is saved on the run (a *checkpoint*), the run becomes `awaiting_approval`, and
   the worker is released. Waiting holds nothing, so a decision can take hours.
3. An owner or admin approves or rejects, on the Approvals tab (or through the API below).
4. A worker resumes the run from the checkpoint:
   - **approved:** the stored arguments run, nothing is asked of the model, and the result goes back
     to it. Calls that followed in the same reply then continue, and may pause again.
   - **rejected:** the model is told "A person rejected this action, so it was not run" (with the
     note, if any) and decides how to finish.
5. If nobody decides in time the approval **expires** and the run stops, without running anything.

The run's time limit applies to each stretch of work. Waiting time is not work time.

## States

| Approval | Meaning |
| --- | --- |
| `pending` | Waiting for a person. At most one per run. |
| `approved` / `rejected` | Decided (who, when, optional note). The run is handed back to a worker. |
| `expired` | Nobody decided in time (24 hours by default, `APPROVAL_EXPIRY_HOURS`, 1 to 168). The run failed; nothing ran. |
| `cancelled` | The run was cancelled or ended first. Nothing ran. |

A step waiting for a decision has status `awaiting_approval`. If it never runs it ends `skipped`.

## API

Under `/api/v1/organizations/{org_id}/approvals`. Viewing: owner, admin, developer. Deciding: owner
and admin only. The agent itself can never decide: a decision needs a signed-in person's token.

| Call | Does |
| --- | --- |
| `GET ""` | The inbox, newest first. Filters `status`, `run_id`, `limit`, `offset`. Use `status=pending` for what waits. |
| `GET /{id}` | One approval: agent and version, tool, the exact `proposed_input`, the model's reason, time left, and who decided. |
| `POST /{id}/approve` | Body `{"note": "..."}` (optional, 500 characters). |
| `POST /{id}/reject` | Same body. The note is shown to the agent. |

A run in `awaiting_approval` also shows `pending_approval` in its detail.

Errors: `404 approval_not_found`; `409 approval_already_decided`, `approval_expired`,
`approval_cancelled`, `approval_not_ready` (the run is a moment away from waiting); `503
queue_unavailable` (see "If something fails").

## The screens

- **Approvals tab** (owners, admins, developers): the inbox, opening on what is waiting, with a
  count on the tab. Filter by status. Each card shows the tool, the agent and version, a one-line
  summary of the action, and the time left. It refreshes by itself while something is waiting.
- **An approval** shows exactly what will run: for Slack the channel and the final message text; for
  an HTTP write the method, address, headers and body; for any tool the exact data. Everything the
  agent wrote is shown as plain text (never as markup or a link). Below it: the agent's own
  explanation, labelled as unchecked, and the decision box.
- **Deciding** (owners and admins): an optional note, then **Reject** (one click) or **Approve**
  (asks you to confirm first). The buttons lock while the request is in flight. If your click is
  refused (someone else decided, or it expired), the reason stays on screen and the page shows
  what really happened. If the decision was saved but the run could not be handed on, a **Try
  again** button appears.
- **A waiting run's page** says it is paused, shows when the request expires, and links to the
  approval ("Review and decide", or "View the request" for developers).
- Members see none of this. Developers see requests but get no decision buttons.

## Why it is safe

| Risk | What prevents it |
| --- | --- |
| Two people decide at once, or someone double clicks | One atomic update succeeds only while the approval is pending, not expired, and its run still waits. The loser gets 409. |
| A late click after expiry or cancel | The same update refuses it, and reading the clock first marks it expired or cancelled. |
| The action runs twice | Only one resume can claim the run (a row lock and a state change). Repeats do nothing. A step is marked started *before* its action runs, and a dead worker's run is never retried. |
| What runs differs from what was shown | The action runs from the approval's stored arguments, re-checked: if checking would change them (for example after a deploy), it is refused. |
| The model sneaks in a different action | After the pause the model is not asked again before the approved action runs. |
| A worker dies mid-action | The run fails saying plainly that it is **unknown whether the action happened**, and it is not retried. A worker that dies *before* the action began is replaced and the action runs once; one that dies *after* it finished is replaced and the recorded result is used, not a second run (see `docs/engine.md`, "Crash recovery"). |
| A run waits for days | A run waiting for a person has no worker and no heartbeat to lose; only a running run can be mistaken for a dead one. |
| Nobody ever decides | Expiry stops the run. Expiry is applied whenever runs or approvals are read or decided. |
| A secret in an approval | Approvals hold only the arguments the agent chose. Credentials are added by the platform when the action runs, never stored with the approval, and the audit log records who and when, not the arguments or the note. |

## If something fails

- **Deciding returns 503 `queue_unavailable`:** the decision is saved but the run was not handed to
  a worker (the queue was down). Press approve or reject again: the same decision on a run that
  still waits hands it over again, and is harmless if it was already picked up.
- **A worker restarted during a resume:** the redelivered task does nothing while the worker is
  alive. If it died, the scheduler takes the run over within about a minute and carries on from the
  same decision; the approved action is run once, never twice. If the action had *started*, the run
  ends with "unknown whether the action happened". Start a new run if you want to try again.
- **The saved state cannot be read** (it came from an incompatible version): the run fails with a
  clear message instead of guessing.

## Known limits

- The action is checked again when it runs. Rules that depend on the integration (an allowed host
  or channel) are therefore enforced at that moment, so a person can approve an action that then
  fails because the host or channel is not allowed. The failure is shown to the agent.
- Self-approval is allowed for now: the person who started a run may approve it.
- The model's stated reason is its own claim, shown for context, not a guarantee.
- No notifications yet: someone has to look at the inbox.
- One decision at a time per run; there is no bulk approve.

## Try it from PowerShell

The script creates an agent whose calculator needs approval and runs it. Answer `l` to leave the request
waiting, then decide it on the Approvals tab. Or decide it from the script:


```powershell
.\scripts\try-approval.ps1                 # asks you to approve or reject
.\scripts\try-approval.ps1 -Decision approve
.\scripts\try-approval.ps1 -Decision reject -Note "Use a spreadsheet instead"
```

## Where the code is

`app/engine/graph.py` (pause and resume), `app/engine/executor.py` (`resume_run`, checkpoints),
`app/engine/recorder.py` (`request_approval`), `app/repositories/approvals.py` and
`app/repositories/runs.py` (the atomic claims), `app/services/approvals.py` (deciding and the
clock), `app/api/v1/approvals.py`; screens in `frontend/src/features/approvals/`. Tests: `tests/integration/test_approvals.py`,
`tests/integration/test_approvals_rules.py`, `tests/test_checkpoint.py`.
