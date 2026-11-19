"""The Slack tool: `slack.send_message`.

Posting to Slack changes something outside the platform, so the tool is sensitive: it always needs
a person's approval (the engine enforces that; see docs/phase4-design.md). On top of that:

* The channel must be one the admin listed on the Slack integration. Anything else is refused
  before anything is sent.
* The request goes only to slack.com, through the same address and TLS checks as the HTTP tools.
  The host is fixed in this file, not chosen by the agent or by the integration.
* The message text is made inert first (`prepare_text`): `@channel`, `@here` and `@everyone` cannot
  ping a whole workspace, and Slack's link and mention markup (`<!channel>`, `<@U123>`,
  `<https://evil|click here>`) is escaped so a message cannot disguise a link. Link previews
  are off.
* The bot token comes from the vault at the moment of the call, is sent only to slack.com, and is
  scrubbed from anything returned. Slack's errors are turned into short, safe messages.
"""

import json
import re
from typing import Any

from pydantic import ValidationError

from app.core.vault import redact_secret
from app.models.enums import IntegrationProvider
from app.schemas.integration import SlackConfig
from app.tools import register
from app.tools.base import ToolContext, ToolError
from app.tools.http import Credential, HttpFetcher
from app.tools.netsafety import SafeUrl

SLACK_HOST = "slack.com"
POST_MESSAGE_PATH = "/api/chat.postMessage"
MAX_TEXT_CHARS = 3_000
ZERO_WIDTH_SPACE = "\u200b"

_CHANNEL = re.compile(r"^[CG][A-Z0-9]{8,20}$")
_BROADCAST = re.compile(r"@(?=(?:channel|here|everyone)\b)", re.IGNORECASE)
# Control characters other than tab, newline and carriage return.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ERROR_CODE = re.compile(r"^[a-z0-9_]{1,50}$")

# What Slack's error codes mean for the person reading the run, in plain words.
_AUTH_REJECTED = "Slack rejected the saved bot token. An admin should save a new one."
_RATE_LIMITED = "Slack is rate limiting this app. Try again later."
_FRIENDLY_ERRORS = {
    "channel_not_found": (
        "Slack cannot find that channel. Check the channel id on the integration."
    ),
    "not_in_channel": (
        "The Slack app is not in that channel. Invite it there first "
        "(in Slack, type /invite and pick the app)."
    ),
    "is_archived": "That Slack channel is archived.",
    "invalid_auth": _AUTH_REJECTED,
    "not_authed": _AUTH_REJECTED,
    "account_inactive": _AUTH_REJECTED,
    "token_revoked": _AUTH_REJECTED,
    "token_expired": _AUTH_REJECTED,
    "missing_scope": (
        "The Slack app lacks the chat:write permission. An admin must add it in the Slack "
        "app settings and reinstall the app."
    ),
    "restricted_action": "Slack does not allow the app to post there.",
    "msg_too_long": "Slack says the message is too long.",
    "no_text": "Slack says the message is empty.",
    "ratelimited": _RATE_LIMITED,
    "rate_limited": _RATE_LIMITED,
}


def prepare_text(text: str) -> str:
    """Make a message inert. Idempotent: preparing prepared text changes nothing."""
    text = _CONTROL.sub("", text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")  # no mention, link or broadcast markup
    return _BROADCAST.sub("@" + ZERO_WIDTH_SPACE, text)  # "@channel" can no longer match


def prepare_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """The channel and text exactly as they will be sent. Idempotent, and used both by the engine
    (so an approver sees the final text) and by the handler itself."""
    channel, text = arguments.get("channel"), arguments.get("text")
    if not isinstance(channel, str) or not isinstance(text, str):
        raise ToolError("channel and text must both be text.")
    channel = channel.strip().upper()
    if not _CHANNEL.match(channel):
        raise ToolError(
            "channel must be a Slack channel id such as C0123456789 (not the channel's name)."
        )
    final = prepare_text(text).strip()
    if not final:
        raise ToolError("The message is empty.")
    if len(final) > MAX_TEXT_CHARS:
        raise ToolError(f"The message is longer than {MAX_TEXT_CHARS} characters.")
    return {"channel": channel, "text": final}


def new_fetcher() -> HttpFetcher:
    """The fetcher used for Slack. Tests replace this to point at a local server."""
    return HttpFetcher()


def interpret_response(result: dict[str, Any], channel: str) -> dict[str, Any]:
    """Turn Slack's answer into a short result, or a ToolError with a safe message."""
    status = int(result.get("status", 0))
    if status == 429:
        retry = str(result.get("retry_after", ""))
        wait = f" Retry after {retry} seconds." if retry.isdigit() else ""
        raise ToolError(f"Slack is rate limiting this app.{wait}")
    if status >= 500:
        raise ToolError(f"Slack had a problem (HTTP {status}). Try again later.")
    if 300 <= status < 400:
        raise ToolError("Slack redirected the request, which is not followed.")
    if result.get("refused"):
        raise ToolError("Slack did not give a usable answer.")
    try:
        data = json.loads(result.get("body") or "")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ToolError(f"Slack did not give a usable answer (HTTP {status}).")
    if data.get("ok") is True:
        timestamp = data.get("ts")
        sent: dict[str, Any] = {"ok": True, "channel": channel, "note": "The message was posted."}
        if isinstance(timestamp, str) and re.fullmatch(r"[0-9.]{1,32}", timestamp):
            sent["message_ts"] = timestamp
        return sent
    code = data.get("error")
    if not isinstance(code, str) or not _ERROR_CODE.match(code):
        raise ToolError("Slack refused the message.")
    raise ToolError(_FRIENDLY_ERRORS.get(code, f"Slack refused the message ({code})."))


@register("slack.send_message", prepare=prepare_arguments)
async def send_message(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    final = prepare_arguments(arguments)  # idempotent, so safe even if the engine did it already
    channel, text = final["channel"], final["text"]

    if context.integrations is None:
        raise ToolError("This tool is not connected to an integration.")
    integration = await context.integrations.resolve(
        context.tool_config.get("integration_id"), IntegrationProvider.SLACK
    )
    try:
        config = SlackConfig.model_validate(integration.config)
    except ValidationError:
        raise ToolError(
            "The integration's settings are invalid. An admin should review them."
        ) from None
    if not config.allowed_channels:
        raise ToolError(
            "This integration does not allow any channels yet. An admin can list them in the "
            "Integrations tab."
        )
    if channel not in config.allowed_channels:
        raise ToolError(
            f"The channel {channel} is not allowed by this integration. Allowed channels: "
            f"{', '.join(config.allowed_channels)}."
        )
    if not integration.secret:
        raise ToolError(
            "This Slack integration has no bot token yet. An admin can add it in the "
            "Integrations tab."
        )

    payload = json.dumps(
        {
            "channel": channel,
            "text": text,
            "parse": "none",
            "link_names": False,
            "unfurl_links": False,
            "unfurl_media": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    result = await new_fetcher().fetch(
        method="POST",
        url=SafeUrl(host=SLACK_HOST, path_and_query=POST_MESSAGE_PATH),
        allowed_hosts=[SLACK_HOST],
        headers=[],
        credential=Credential(header="Authorization", value=f"Bearer {integration.secret}"),
        body=payload,
        content_type="application/json; charset=utf-8",
    )
    cleaned: dict[str, Any] = redact_secret(result, integration.secret)
    return interpret_response(cleaned, channel)
