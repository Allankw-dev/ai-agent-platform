# Agents and versions

An **agent** is a named configuration of an AI model plus the tools it may use. Everything that
defines its behaviour is saved as an immutable **version**.

## Versions

- Creating an agent makes version 1. Editing never changes a version: it adds a new one
  (`POST .../versions`) and points the agent at it. Old versions stay readable forever.
- **Rollback** (`POST .../rollback`) points the agent at an earlier version. Nothing is deleted, and
  the next edit continues the numbering (never reuses a number).
- The database enforces this: the runtime role can insert and read `agent_versions` and
  `agent_tools` but cannot update or delete them (migration 0005).
- Concurrent edits of one agent are serialized with a row lock, so version numbers never collide.
- **Duplicate** copies the current version into a new draft agent (`<name> (copy)`).
- **Delete** is soft: the agent leaves lists and cannot run; its versions and runs are kept, and its
  name becomes available again.

## What a version contains

| Field | Rules |
| --- | --- |
| `provider`, `model` | Provider must be enabled (`ENABLED_LLM_PROVIDERS`, default `gemini`). Model names are free text limited to letters, digits and `. _ : / -`: model names change often, so they are not hardcoded. |
| `system_instructions` | Required, up to 20,000 characters. |
| `objectives` | Optional, up to 4,000 characters. |
| `model_params` | Only `max_output_tokens`. There is deliberately no temperature: newer models reject non-default values. |
| `memory_config` | `conversation_memory`, `max_history_messages`. |
| `limits` | `max_iterations`, `timeout_seconds`, `max_total_tokens`, optional `cost_budget_usd`. Defaults 10 / 120 / 50,000 / none. |
| `tools` | Tool keys from the catalog (`GET /tools`), each with `requires_approval` and a small `config`. |

Platform ceilings cap every limit (`AGENT_*_CEILING` settings: 25 iterations, 300 seconds,
500,000 tokens, $5). A sensitive tool always requires approval; the API forces it even if the
request says otherwise.

## Permissions

Everyone in an organization can view agents. Owners, admins and developers can create, edit,
version, roll back, duplicate, enable/disable and delete them. Starting and cancelling runs is limited to the
same roles; everyone can view runs. See `docs/engine.md`.

## In the app

Organization pages have an **Agents** tab (`/orgs/{org}/agents`):

- **List:** search by name, filter by status, and see each agent's status, version and model.
- **Create / edit:** one form for details, behavior (model, instructions, objectives), tools, and
  limits. The model is free text with suggestions, because model names change.
- **Saving an edit:** changed behavior is saved as a **new version**; a changed name or
  description updates the agent itself. Only what changed is sent, and saving with no changes
  does nothing. If the new version saves but the rename is refused (for example the name is
  taken), the page says so.
- **Agent page:** the current configuration, **Activate / Disable / Enable**, **Duplicate**,
  **Delete** (with confirmation), and the **version history**, where any version can be viewed and
  (by managers) restored.
- **Roles:** members see everything read-only. The buttons follow the same rules as the API, and
  the API enforces them regardless.
- **Not in the form yet:** per-tool settings and conversation memory are kept as they were when
  editing, but cannot be changed from the screen.

## Providers

Each version names its provider, so the engine can support several. Gemini is first. The free
Gemini tier lets Google use prompts to improve its products, so use fake or public data only until
you move to a paid key (`GEMINI_TIER=paid`).
