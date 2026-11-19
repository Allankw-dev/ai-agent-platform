"""The Slack tool, against a real local HTTPS server standing in for slack.com (TLS verified)."""

import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from app.models.enums import IntegrationProvider
from app.tools import get_handler, prepare_arguments
from app.tools import slack as slack_tools
from app.tools.base import ResolvedIntegration, ToolContext, ToolError
from app.tools.http import HttpFetcher
from app.tools.netsafety import SafeNetworkBackend
from tests.tls_server import LocalHttpsServer, Reply, Seen, local_fetcher

TOKEN = "xoxb-1111-2222-SUPER-SECRET-bot-token"
INTEGRATION_ID = uuid.uuid4()
CHANNEL = "C0123456789"
OTHER_CHANNEL = "C0999999999"
ENDPOINT = "/api/chat.postMessage"
# The published limit, written out here on purpose rather than imported from the code.
MAX_CHARS = 3_000


@pytest.fixture
async def server(tmp_path: Path) -> AsyncIterator[LocalHttpsServer]:
    local = LocalHttpsServer(tmp_path)
    await local.start()
    local.on(ENDPOINT, Reply(body=json.dumps({"ok": True, "ts": "1700000000.000100"})))
    yield local
    await local.stop()


class FakeAccess:
    def __init__(self, config: dict[str, Any], secret: str | None = TOKEN) -> None:
        self.config = config
        self.secret = secret

    async def resolve(
        self, integration_id: object, provider: IntegrationProvider
    ) -> ResolvedIntegration:
        assert provider is IntegrationProvider.SLACK
        return ResolvedIntegration(
            id=INTEGRATION_ID,
            provider=provider,
            name="Team Slack",
            config=self.config,
            secret=self.secret,
        )


def context(config: dict[str, Any] | None = None, secret: str | None = TOKEN) -> ToolContext:
    return ToolContext(
        org_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        integrations=FakeAccess(config or {"allowed_channels": [CHANNEL]}, secret),
        tool_config={"integration_id": str(INTEGRATION_ID)},
    )


@pytest.fixture
def send(server: LocalHttpsServer, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(slack_tools, "new_fetcher", lambda: local_fetcher(server))

    async def run(
        arguments: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        secret: str | None = TOKEN,
    ) -> dict[str, Any]:
        handler = get_handler("slack.send_message")
        assert handler is not None
        return await handler(arguments, context(config, secret))

    return run


def message(text: str = "Hello team", channel: str = CHANNEL) -> dict[str, Any]:
    return {"channel": channel, "text": text}


def sent_body(server: LocalHttpsServer) -> dict[str, Any]:
    (seen,) = server.seen
    body: dict[str, Any] = json.loads(seen.body)
    return body


# ---------- a message is sent, the right way ----------


async def test_a_message_is_posted_with_the_bot_token(send: Any, server: LocalHttpsServer) -> None:
    result = await send(message("Deploy finished"))
    assert result == {
        "ok": True,
        "channel": CHANNEL,
        "note": "The message was posted.",
        "message_ts": "1700000000.000100",
    }
    (seen,) = server.seen
    assert (seen.method, seen.target) == ("POST", ENDPOINT)
    assert seen.host == "slack.com"  # fixed: nothing the agent or the integration says changes it
    assert seen.headers["authorization"] == f"Bearer {TOKEN}"
    assert seen.headers["content-type"] == "application/json; charset=utf-8"
    assert sent_body(server) == {
        "channel": CHANNEL,
        "text": "Deploy finished",
        "parse": "none",
        "link_names": False,
        "unfurl_links": False,
        "unfurl_media": False,
    }


async def test_the_channel_is_normalised(send: Any, server: LocalHttpsServer) -> None:
    await send(message(channel=f"  {CHANNEL.lower()} "))
    assert sent_body(server)["channel"] == CHANNEL


async def test_a_private_channel_id_works_too(send: Any, server: LocalHttpsServer) -> None:
    await send(message(channel="G0123456789"), config={"allowed_channels": ["G0123456789"]})
    assert sent_body(server)["channel"] == "G0123456789"


async def test_unicode_and_newlines_are_kept(send: Any, server: LocalHttpsServer) -> None:
    await send(message("Habari ya asubuhi ☀️\nline two\tindented"))
    assert sent_body(server)["text"] == "Habari ya asubuhi ☀️\nline two\tindented"


# ---------- only channels the admin listed ----------


async def test_a_channel_that_is_not_listed_is_refused_before_anything_is_sent(
    send: Any, server: LocalHttpsServer
) -> None:
    with pytest.raises(ToolError, match="not allowed by this integration") as caught:
        await send(message(channel=OTHER_CHANNEL))
    assert CHANNEL in str(caught.value)  # the model is told what it may use
    assert server.seen == []


async def test_an_integration_with_no_channels_refuses_everything(
    send: Any, server: LocalHttpsServer
) -> None:
    with pytest.raises(ToolError, match="does not allow any channels"):
        await send(message(), config={"allowed_channels": []})
    assert server.seen == []


@pytest.mark.parametrize(
    "channel",
    [
        "general",
        "#general",
        "C1",
        "U0123456789",
        "D0123456789",
        "C01234567890123456789012",
        "",
        "  ",
    ],
)
async def test_something_that_is_not_a_channel_id_is_refused(
    send: Any, server: LocalHttpsServer, channel: str
) -> None:
    with pytest.raises(ToolError, match="channel id"):
        await send(message(channel=channel))
    assert server.seen == []


async def test_the_allowed_channels_are_read_fresh_from_the_integration(
    send: Any, server: LocalHttpsServer
) -> None:
    await send(message())
    with pytest.raises(ToolError, match="not allowed"):
        await send(message(), config={"allowed_channels": [OTHER_CHANNEL]})
    assert len(server.seen) == 1


async def test_without_a_bot_token_nothing_is_sent(send: Any, server: LocalHttpsServer) -> None:
    with pytest.raises(ToolError, match="no bot token yet"):
        await send(message(), secret=None)
    assert server.seen == []


# ---------- the text is made inert ----------

PINGS = [
    "@channel",
    "@here",
    "@everyone",
    "@CHANNEL",
    "@Here now",
    "hey @channel, deploy done",
    "<!channel>",
    "<!here|here>",
    "<!everyone>",
    "<!subteam^S0123ABC|@oncall>",
    "<@U0123456789>",
    "<#C0123456789|general>",
    "<https://evil.example.net|click here to log in>",
    "<mailto:boss@example.com|email me>",
    "<!date^1700000000^{date}|fallback>",
    "&lt;!channel&gt;",
]


@pytest.mark.parametrize("text", PINGS)
async def test_a_message_cannot_ping_the_workspace_or_hide_a_link(
    send: Any, server: LocalHttpsServer, text: str
) -> None:
    await send(message(text))
    delivered = sent_body(server)["text"]
    assert "<" not in delivered and ">" not in delivered  # no Slack markup survives
    assert not re.search(r"(?i)@(channel|here|everyone)\b", delivered)  # no broadcast words
    # Nothing is lost for a reader: the words are all still there.
    assert delivered.replace("\u200b", "") == text.replace("<", "&lt;").replace(">", "&gt;")


@pytest.mark.parametrize("text", PINGS + ["plain text", "a < b > c", "x" * 50, "@alice", "@"])
def test_preparing_text_twice_changes_nothing(text: str) -> None:
    once = slack_tools.prepare_text(text)
    assert slack_tools.prepare_text(once) == once


def test_the_prepared_arguments_are_final_and_idempotent() -> None:
    raw = {"channel": f" {CHANNEL.lower()} ", "text": "  hi <!channel> & @here  "}
    prepared = prepare_arguments("slack.send_message", raw)
    assert prepared["channel"] == CHANNEL
    assert "<" not in prepared["text"] and prepared["text"] == prepared["text"].strip()
    assert prepare_arguments("slack.send_message", prepared) == prepared


def test_other_tools_are_not_touched_by_preparation() -> None:
    arguments = {"url": "https://api.example.com/<x>"}
    assert prepare_arguments("http.get", arguments) is arguments
    assert prepare_arguments("no.such_tool", arguments) is arguments


async def test_control_characters_are_removed(send: Any, server: LocalHttpsServer) -> None:
    await send(message("a\x00b\x07c\x1bd\x7fe"))
    assert sent_body(server)["text"] == "abcde"


# ---------- limits ----------


@pytest.mark.parametrize("text", ["", "   ", "\n\t ", "\x00\x01"])
async def test_an_empty_message_is_refused(send: Any, server: LocalHttpsServer, text: str) -> None:
    with pytest.raises(ToolError, match="empty"):
        await send(message(text))
    assert server.seen == []


async def test_the_length_limit_is_exactly_3000_characters(
    send: Any, server: LocalHttpsServer
) -> None:
    await send(message("a" * MAX_CHARS))
    assert len(sent_body(server)["text"]) == MAX_CHARS
    server.seen.clear()
    with pytest.raises(ToolError, match="longer than 3000"):
        await send(message("a" * (MAX_CHARS + 1)))
    assert server.seen == []


async def test_the_limit_applies_to_the_text_that_will_really_be_sent(
    send: Any, server: LocalHttpsServer
) -> None:
    """Escaping makes `<` longer, and the approver sees the escaped text, so that is what counts."""
    with pytest.raises(ToolError, match="longer than 3000"):
        await send(message("<" * (MAX_CHARS // 2)))
    assert server.seen == []


@pytest.mark.parametrize("bad", [None, 5, ["hi"], {"a": 1}])
async def test_text_and_channel_must_be_text(send: Any, bad: Any) -> None:
    with pytest.raises(ToolError, match="must both be text"):
        await send({"channel": CHANNEL, "text": bad})
    with pytest.raises(ToolError, match="must both be text"):
        await send({"channel": bad, "text": "hi"})


# ---------- what Slack says back ----------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("channel_not_found", "cannot find that channel"),
        ("not_in_channel", "not in that channel"),
        ("is_archived", "archived"),
        ("invalid_auth", "rejected the saved bot token"),
        ("token_revoked", "rejected the saved bot token"),
        ("missing_scope", "chat:write"),
        ("ratelimited", "rate limiting"),
        ("some_new_error", r"refused the message \(some_new_error\)"),
    ],
)
async def test_slack_errors_become_short_plain_messages(
    send: Any, server: LocalHttpsServer, error: str, expected: str
) -> None:
    server.on(ENDPOINT, Reply(body=json.dumps({"ok": False, "error": error})))
    with pytest.raises(ToolError, match=expected) as caught:
        await send(message())
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    "error",
    ["Bad Error With Spaces", "x" * 80, f"echo {TOKEN}", "line\nbreak", 5, None, ["a"]],
)
async def test_an_odd_error_value_from_slack_is_never_passed_on(
    send: Any, server: LocalHttpsServer, error: Any
) -> None:
    server.on(ENDPOINT, Reply(body=json.dumps({"ok": False, "error": error})))
    with pytest.raises(ToolError) as caught:
        await send(message())
    assert str(caught.value) == "Slack refused the message."


async def test_a_token_echoed_as_the_error_code_is_scrubbed(
    send: Any, server: LocalHttpsServer
) -> None:
    """A token made only of lowercase letters, digits and underscores looks like a harmless error
    code. If a server echoed it back that way it would reach the model, unless it is scrubbed."""
    plain_token = "xoxbplain_token_9876543210"
    server.on(ENDPOINT, Reply(body=json.dumps({"ok": False, "error": plain_token})))
    with pytest.raises(ToolError) as caught:
        await send(message(), secret=plain_token)
    assert plain_token not in str(caught.value)
    assert str(caught.value) == "Slack refused the message."


async def test_a_rate_limit_says_how_long_to_wait(send: Any, server: LocalHttpsServer) -> None:
    server.on(ENDPOINT, Reply(status=429, headers={"Retry-After": "30"}, body="{}"))
    with pytest.raises(ToolError, match=r"rate limiting.*Retry after 30 seconds"):
        await send(message())


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (Reply(status=500, body="oops"), "Slack had a problem"),
        (Reply(status=503, body="down"), "Slack had a problem"),
        (Reply(body="<html>not json</html>"), "usable answer"),
        (Reply(body="[1, 2]"), "usable answer"),
        (Reply(body=""), "usable answer"),
        (Reply(status=302, headers={"Location": "https://evil.example.net/"}), "redirected"),
        (Reply(body=b"\x89PNG", content_type="image/png"), "usable answer"),
    ],
)
async def test_unusable_answers_are_reported_plainly(
    send: Any, server: LocalHttpsServer, reply: Reply, expected: str
) -> None:
    server.on(ENDPOINT, reply)
    with pytest.raises(ToolError, match=expected):
        await send(message())
    assert len(server.seen) == 1  # a redirect, in particular, is never followed


async def test_a_success_reply_keeps_only_a_clean_timestamp(
    send: Any, server: LocalHttpsServer
) -> None:
    server.on(
        ENDPOINT,
        Reply(body=json.dumps({"ok": True, "ts": "<script>", "message": {"text": "full echo"}})),
    )
    result = await send(message())
    assert result == {"ok": True, "channel": CHANNEL, "note": "The message was posted."}


async def test_the_token_never_appears_in_a_result(send: Any, server: LocalHttpsServer) -> None:
    server.on(
        ENDPOINT,
        lambda seen: Reply(body=json.dumps({"ok": True, "ts": "1.2", "debug": seen.headers})),
    )
    result = await send(message())
    assert TOKEN not in json.dumps(result)


# ---------- the connection itself ----------


@pytest.mark.parametrize("answer", [["127.0.0.1"], ["10.0.0.9"], ["169.254.169.254"], ["::1"]])
async def test_the_address_check_applies_to_slack_too(
    server: LocalHttpsServer, monkeypatch: pytest.MonkeyPatch, answer: list[str]
) -> None:
    async def resolver(host: str, port: int) -> list[str]:
        return answer

    backend = SafeNetworkBackend(resolver=resolver, port_override=server.port)
    monkeypatch.setattr(
        slack_tools,
        "new_fetcher",
        lambda: HttpFetcher(backend=backend, ssl_context=server.client_context()),
    )
    handler = get_handler("slack.send_message")
    assert handler is not None
    with pytest.raises(ToolError, match="public internet address"):
        await handler(message(), context())
    assert server.seen == []


async def test_an_untrusted_certificate_is_refused(
    server: LocalHttpsServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ssl

    backend = SafeNetworkBackend(
        resolver=lambda host, port: _loopback(),
        address_check=lambda addresses: [__import__("ipaddress").ip_address(a) for a in addresses],
        port_override=server.port,
    )
    monkeypatch.setattr(
        slack_tools,
        "new_fetcher",
        lambda: HttpFetcher(backend=backend, ssl_context=ssl.create_default_context()),
    )
    handler = get_handler("slack.send_message")
    assert handler is not None
    with pytest.raises(ToolError, match="certificate"):
        await handler(message(), context())
    assert server.seen == []


async def _loopback() -> list[str]:
    return ["127.0.0.1"]


async def test_without_integration_access_the_tool_says_so() -> None:
    handler = get_handler("slack.send_message")
    assert handler is not None
    bare = ToolContext(org_id=uuid.uuid4(), agent_id=uuid.uuid4(), run_id=uuid.uuid4())
    with pytest.raises(ToolError, match="not connected to an integration"):
        await handler(message(), bare)


async def test_settings_that_do_not_belong_to_slack_are_refused(
    send: Any, server: LocalHttpsServer
) -> None:
    with pytest.raises(ToolError, match="settings are invalid"):
        await send(message(), config={"allowed_hosts": ["api.example.com"]})
    assert server.seen == []


def test_seen_is_the_request_the_server_received() -> None:
    assert (
        Seen(method="POST", target="/", headers={"host": "slack.com"}, body=b"").host == "slack.com"
    )
