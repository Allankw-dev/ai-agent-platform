# Slack tool

`slack.send_message` lets an agent post a message to a Slack channel. It needs a **Slack
integration**, which holds the bot token (saved in the vault, see `docs/credentials.md`) and the
channels that may be posted to.

Posting sends a real message to real people, so the tool is **sensitive: it always needs a person's
approval.** Until approvals exist (step 4D) the engine skips it and nothing is sent.

## Setting it up

1. **Integrations tab:** add a *Slack* integration. List the allowed channels, one Slack channel id
   per line (like `C0123456789`; ids, not names), and save the bot token (`xoxb-...`).
2. **Agent form:** tick *Send Slack message* and choose the integration (chosen for you if only one
   fits). The approval switch is locked on.

### Getting a bot token and channel id (use a throwaway workspace)

1. Create a free workspace at https://slack.com/create if you do not have a test one.
2. Go to https://api.slack.com/apps, click **Create New App**, **From scratch**, name it, and pick
   the test workspace.
3. Open **OAuth & Permissions**, and under **Bot Token Scopes** add `chat:write`.
4. Click **Install to Workspace** and allow it. Copy the **Bot User OAuth Token** (starts `xoxb-`).
5. In Slack, create a channel for tests, and invite the app: type `/invite @YourAppName` there.
6. Get the channel id: open the channel, click its name at the top, and the id is at the bottom of
   the **About** tab (it looks like `C0123456789`).

## What the agent sends

`channel` (a Slack channel id) and `text` (up to 3,000 characters).

## Rules enforced on every call

| Rule | Detail |
| --- | --- |
| Channels | Only ids on the integration's list, read when the tool runs, so an admin's edit applies at once. An empty list allows nothing. Names such as `#general` are refused. |
| Where it goes | Only `https://slack.com/api/chat.postMessage`. The host is fixed in the code; neither the agent nor the integration can change it. It uses the same address and TLS checks as the HTTP tools (`docs/http-tools.md`), and redirects are never followed. |
| Mentions | `@channel`, `@here` and `@everyone` get an invisible character after the `@` so they cannot ping a workspace, and the Slack request sets `link_names` off. |
| Link markup | `<` and `>` are escaped, so `<!channel>`, `<@U123>`, `<#C123>` and `<https://evil\|click here>` appear as plain text instead of acting as mentions or disguised links. Link previews are off. |
| Text | Control characters removed, leading and trailing space trimmed, empty text refused, 3,000 characters at most, counted on the text that is really sent. |
| Token | From the vault at the moment of the call, sent only to slack.com, scrubbed from anything returned. |
| Slack's answers | Only `ok`, the channel and a clean timestamp come back. Errors become short plain messages (for example "The Slack app is not in that channel. Invite it there first"). An unexpected error value from Slack is never passed on. Rate limits say how long to wait. |

## The exact text an approver sees

The engine runs each tool's *argument preparer* after the arguments pass the schema and before the
tool runs. For Slack it produces the channel and text exactly as they will be sent. Preparing twice
changes nothing, so the handler can safely prepare again. Step 4D records the prepared arguments in
the approval, and the approval screens show them, so what a person approves is what is posted.

## Where the code is

- `app/tools/slack.py`: the handler, `prepare_text`, `prepare_arguments`, error handling.
- `app/tools/__init__.py`: the registry, including `prepare_arguments`.
- Tests: `tests/test_slack_tool.py` (a local HTTPS server standing in for slack.com),
  `tests/integration/test_slack_tool_db.py` (real vault and database) and
  `tests/integration/test_agent_tool_integrations.py` (assigning the tool).
