"""The HTTP tools, against a real local HTTPS server (TLS is verified; no internet is used)."""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from app.models.enums import IntegrationProvider
from app.tools import get_handler
from app.tools import http as http_tools
from app.tools.base import ResolvedIntegration, ToolContext, ToolError, validate_arguments
from app.tools.http import HttpFetcher
from app.tools.netsafety import SafeNetworkBackend
from tests.tls_server import LocalHttpsServer, Reply, Seen

# The published limits, written out here on purpose: a test that imported the code's own
# constants would pass whatever they were changed to.
ONE_MB = 1_000_000
HUNDRED_KB = 100_000

SECRET = "sk-live-VERY-SECRET-key-123"
INTEGRATION_ID = uuid.uuid4()
HOST = "api.example.com"


def allow_everything(addresses: Any) -> Any:
    import ipaddress

    return [ipaddress.ip_address(a) for a in addresses]


async def loopback(host: str, port: int) -> list[str]:
    return ["127.0.0.1"]


@pytest.fixture
async def server(tmp_path: Path) -> AsyncIterator[LocalHttpsServer]:
    local = LocalHttpsServer(tmp_path)
    await local.start()
    yield local
    await local.stop()


def fetcher_for(server: LocalHttpsServer) -> HttpFetcher:
    backend = SafeNetworkBackend(
        resolver=loopback, address_check=allow_everything, port_override=server.port
    )
    return HttpFetcher(backend=backend, ssl_context=server.client_context())


class FakeAccess:
    """Stands in for the database: hands the handler one integration."""

    def __init__(self, config: dict[str, Any], secret: str | None = SECRET) -> None:
        self.config = config
        self.secret = secret
        self.asked: list[object] = []

    async def resolve(
        self, integration_id: object, provider: IntegrationProvider
    ) -> ResolvedIntegration:
        self.asked.append(integration_id)
        assert provider is IntegrationProvider.HTTP
        return ResolvedIntegration(
            id=INTEGRATION_ID,
            provider=provider,
            name="Weather API",
            config=self.config,
            secret=self.secret,
        )


def config(**overrides: Any) -> dict[str, Any]:
    return {
        "allowed_hosts": [HOST, "other.example.com"],
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        **overrides,
    }


@pytest.fixture
def use(server: LocalHttpsServer, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point the tools at the local server and return a function that runs one tool call."""
    monkeypatch.setattr(http_tools, "new_fetcher", lambda: fetcher_for(server))

    async def run(
        key: str,
        arguments: dict[str, Any],
        *,
        cfg: dict[str, Any] | None = None,
        secret: str | None = SECRET,
    ) -> dict[str, Any]:
        access = FakeAccess(cfg if cfg is not None else config(), secret)
        context = ToolContext(
            org_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            integrations=access,
            tool_config={"integration_id": str(INTEGRATION_ID)},
        )
        handler = get_handler(key)
        assert handler is not None
        return await handler(arguments, context)

    return run


def get(path: str = "/data", **extra: Any) -> dict[str, Any]:
    return {"url": f"https://{HOST}{path}", **extra}


# ---------- http.get: the happy path and what is sent ----------


async def test_get_returns_status_type_and_body(use: Any, server: LocalHttpsServer) -> None:
    server.on("/data", Reply(body='{"temp": 21}'))
    result = await use("http.get", get())
    assert result["ok"] is True and result["status"] == 200
    assert result["content_type"] == "application/json"
    assert json.loads(result["body"]) == {"temp": 21}
    assert result["truncated"] is False and result["redirects_followed"] == 0
    assert "untrusted" in result["notice"]


async def test_get_sends_the_credential_and_safe_defaults(
    use: Any, server: LocalHttpsServer
) -> None:
    server.on("/data", Reply(body="{}"))
    await use("http.get", get("/data?city=Nairobi"))
    (seen,) = server.seen
    assert (seen.method, seen.target) == ("GET", "/data?city=Nairobi")
    assert seen.host == HOST
    assert seen.headers["authorization"] == f"Bearer {SECRET}"
    assert seen.headers["accept-encoding"] == "identity"
    assert seen.headers["user-agent"].startswith("AgentPlatform/")
    assert seen.body == b""


async def test_the_credential_header_and_scheme_follow_the_integration(
    use: Any, server: LocalHttpsServer
) -> None:
    server.on("/data", Reply(body="{}"))
    await use("http.get", get(), cfg=config(auth_header="X-API-Key", auth_scheme=""))
    (seen,) = server.seen
    assert seen.headers["x-api-key"] == SECRET
    assert "authorization" not in seen.headers


async def test_without_a_saved_secret_no_credential_is_sent(
    use: Any, server: LocalHttpsServer
) -> None:
    server.on("/data", Reply(body="{}"))
    await use("http.get", get(), secret=None)
    assert "authorization" not in server.seen[0].headers


async def test_extra_headers_from_the_agent_are_sent(use: Any, server: LocalHttpsServer) -> None:
    server.on("/data", Reply(body="{}"))
    await use("http.get", get(headers=[{"name": "Accept", "value": "application/json"}]))
    assert server.seen[0].headers["accept"] == "application/json"


async def test_an_error_status_is_returned_to_the_model_not_raised(
    use: Any, server: LocalHttpsServer
) -> None:
    server.on("/data", Reply(status=404, body='{"error": "no such city"}'))
    result = await use("http.get", get())
    assert result["ok"] is False and result["status"] == 404
    assert "no such city" in result["body"]


async def test_text_in_another_charset_is_decoded(use: Any, server: LocalHttpsServer) -> None:
    server.on(
        "/data",
        Reply(body="café".encode("latin-1"), content_type="text/plain; charset=iso-8859-1"),
    )
    assert (await use("http.get", get()))["body"] == "café"


# ---------- which hosts may be called ----------


async def test_a_host_outside_the_allowed_list_is_never_contacted(
    use: Any, server: LocalHttpsServer
) -> None:
    with pytest.raises(ToolError, match="not allowed by this integration"):
        await use("http.get", {"url": "https://evil.example.net/steal"})
    assert server.seen == []


async def test_an_integration_with_no_hosts_refuses_everything(
    use: Any, server: LocalHttpsServer
) -> None:
    with pytest.raises(ToolError, match="does not allow any hosts"):
        await use("http.get", get(), cfg=config(allowed_hosts=[]))
    assert server.seen == []


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/data",
        "https://api.example.com:8443/data",
        "https://user:pw@api.example.com/data",
        "https://api.example.com@evil.example.net/data",
        "https://127.0.0.1/data",
        "https://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ],
)
async def test_unsafe_urls_are_refused_before_any_connection(
    use: Any, server: LocalHttpsServer, url: str
) -> None:
    with pytest.raises(ToolError):
        await use("http.get", {"url": url})
    assert server.seen == []


async def test_the_allowed_host_list_is_read_fresh_from_the_integration(
    use: Any, server: LocalHttpsServer
) -> None:
    """An admin removing a host takes effect on the next call, even for a saved agent version."""
    server.on("/data", Reply(body="{}"))
    await use("http.get", get())
    with pytest.raises(ToolError, match="not allowed"):
        await use("http.get", get(), cfg=config(allowed_hosts=["other.example.com"]))


# ---------- the agent cannot steer the credential or the connection ----------


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "authorization",
        "Host",
        "Cookie",
        "Proxy-Authorization",
        "Proxy-Anything",
        "Sec-Fetch-Mode",
        "Connection",
        "Content-Length",
        "Transfer-Encoding",
        "Upgrade",
        "X-Forwarded-For",
        "Accept-Encoding",
        "User-Agent",
    ],
)
async def test_reserved_headers_cannot_be_set(
    use: Any, server: LocalHttpsServer, name: str
) -> None:
    with pytest.raises(ToolError, match="set by the platform"):
        await use("http.get", get(headers=[{"name": name, "value": "x"}]))
    assert server.seen == []


@pytest.mark.parametrize("name", ["Authorization", "Proxy-Authorization", "Cookie"])
async def test_authorization_is_reserved_even_when_the_credential_uses_another_header(
    use: Any, server: LocalHttpsServer, name: str
) -> None:
    """If the integration sends its key as X-API-Key, the agent still cannot add its own
    Authorization (or cookie) header to ride along on the call."""
    with pytest.raises(ToolError, match="set by the platform"):
        await use(
            "http.get",
            get(headers=[{"name": name, "value": "Bearer stolen"}]),
            cfg=config(auth_header="X-API-Key", auth_scheme=""),
        )
    assert server.seen == []


async def test_the_integrations_own_credential_header_is_reserved_too(
    use: Any, server: LocalHttpsServer
) -> None:
    with pytest.raises(ToolError, match="set by the platform"):
        await use(
            "http.get",
            get(headers=[{"name": "x-api-key", "value": "mine"}]),
            cfg=config(auth_header="X-API-Key", auth_scheme=""),
        )
    assert server.seen == []


@pytest.mark.parametrize(
    "headers",
    [
        [{"name": "X-A", "value": "line\r\nInjected: 1"}],
        [{"name": "X-A", "value": "tab\x00nul"}],
        [{"name": "X-A", "value": "é"}],
        [{"name": "X-A", "value": "v"}, {"name": "x-a", "value": "w"}],
        [{"name": "Bad Name", "value": "v"}],
        [{"name": "X-A\r\nB", "value": "v"}],
        [{"name": "X-A", "value": "v" * 501}],
        [{"name": f"X-{i}", "value": "v"} for i in range(11)],
        ["X-A: v"],
        {"X-A": "v"},
    ],
)
async def test_malformed_headers_are_refused(
    use: Any, server: LocalHttpsServer, headers: Any
) -> None:
    with pytest.raises(ToolError):
        await use("http.get", get(headers=headers))
    assert server.seen == []


# ---------- the secret never comes back ----------


async def test_a_secret_echoed_by_the_server_is_scrubbed(
    use: Any, server: LocalHttpsServer
) -> None:
    def echo(seen: Seen) -> Reply:
        return Reply(body=json.dumps({"you_sent": seen.headers["authorization"], "k": SECRET}))

    server.on("/echo", echo)
    result = await use("http.get", get("/echo"))
    assert SECRET not in json.dumps(result)
    assert "[redacted]" in result["body"]


async def test_errors_do_not_contain_the_secret(use: Any, server: LocalHttpsServer) -> None:
    for arguments in [
        {"url": "https://evil.example.net/"},
        {"url": "http://api.example.com/"},
        get(headers=[{"name": "Authorization", "value": "x"}]),
    ]:
        with pytest.raises(ToolError) as caught:
            await use("http.get", arguments)
        assert SECRET not in str(caught.value)


def test_the_resolved_integration_and_credential_hide_the_secret_in_reprs() -> None:
    resolved = ResolvedIntegration(
        id=INTEGRATION_ID,
        provider=IntegrationProvider.HTTP,
        name="x",
        config={},
        secret=SECRET,
    )
    assert SECRET not in repr(resolved) and SECRET not in str(resolved)
    assert SECRET not in repr(http_tools.Credential(header="Authorization", value=SECRET))


# ---------- what may come back ----------


async def test_binary_responses_are_not_returned(use: Any, server: LocalHttpsServer) -> None:
    server.on("/img", Reply(body=b"\x89PNG\r\n\x1a\n\x00\x01", content_type="image/png"))
    result = await use("http.get", get("/img"))
    assert result["body"] == "" and "not text or JSON" in result["refused"]


async def test_compressed_responses_are_refused(use: Any, server: LocalHttpsServer) -> None:
    server.on("/z", Reply(body=b"\x1f\x8b\x08\x00", headers={"Content-Encoding": "gzip"}))
    result = await use("http.get", get("/z"))
    assert result["body"] == "" and "compressed" in result["refused"]


async def test_a_reply_without_a_type_is_text_only_if_it_decodes(
    use: Any, server: LocalHttpsServer
) -> None:
    server.on("/plain", Reply(body="hello", content_type=None))
    server.on("/bin", Reply(body=b"\xff\xfe\x00\x80", content_type=None))
    assert (await use("http.get", get("/plain")))["body"] == "hello"
    assert "refused" in await use("http.get", get("/bin"))


@pytest.mark.parametrize(
    "content_type",
    ["text/html; charset=utf-8", "application/xml", "application/vnd.api+json", "text/csv"],
)
async def test_text_like_types_are_returned(
    use: Any, server: LocalHttpsServer, content_type: str
) -> None:
    server.on("/t", Reply(body="<x/>", content_type=content_type))
    assert (await use("http.get", get("/t")))["body"] == "<x/>"


async def test_a_huge_response_is_cut_off(use: Any, server: LocalHttpsServer) -> None:
    server.on("/big", Reply(body=b"a" * (ONE_MB * 2), content_type="text/plain"))
    result = await use("http.get", get("/big"))
    assert result["truncated"] is True
    assert len(result["body"]) == ONE_MB


async def test_a_response_exactly_at_the_limit_is_not_marked_truncated(
    use: Any, server: LocalHttpsServer
) -> None:
    server.on("/edge", Reply(body=b"a" * ONE_MB, content_type="text/plain"))
    result = await use("http.get", get("/edge"))
    assert result["truncated"] is False and len(result["body"]) == ONE_MB


# ---------- redirects ----------


async def test_a_get_follows_redirects_within_the_rules(use: Any, server: LocalHttpsServer) -> None:
    server.on("/a", Reply(status=302, headers={"Location": "/b"}, body=""))
    server.on("/b", Reply(status=301, headers={"Location": f"https://{HOST}/c"}, body=""))
    server.on("/c", Reply(body='{"done": true}'))
    result = await use("http.get", get("/a"))
    assert result["status"] == 200 and result["redirects_followed"] == 2
    assert result["url"] == f"https://{HOST}/c"
    # The same host keeps its credential on every hop.
    assert all(s.headers.get("authorization") == f"Bearer {SECRET}" for s in server.seen)


async def test_the_credential_is_never_sent_to_a_different_host(
    use: Any, server: LocalHttpsServer
) -> None:
    server.on(
        "/go", Reply(status=302, headers={"Location": "https://other.example.com/landing"}, body="")
    )
    server.on("/landing", Reply(body='{"landed": true}'))
    result = await use("http.get", get("/go"))
    assert result["status"] == 200
    first, second = server.seen
    assert first.host == HOST and "authorization" in first.headers
    assert second.host == "other.example.com" and "authorization" not in second.headers


async def test_a_redirect_to_a_host_that_is_not_allowed_is_refused(
    use: Any, server: LocalHttpsServer
) -> None:
    server.on("/go", Reply(status=302, headers={"Location": "https://evil.example.net/x"}, body=""))
    with pytest.raises(ToolError, match="does not allow"):
        await use("http.get", get("/go"))
    assert len(server.seen) == 1  # the second hop was never contacted


@pytest.mark.parametrize(
    "location",
    [
        "http://api.example.com/plain",
        "https://127.0.0.1/",
        "https://api.example.com:8443/",
        "https://user:pw@api.example.com/",
        "file:///etc/passwd",
    ],
)
async def test_a_redirect_to_an_unsafe_url_is_refused(
    use: Any, server: LocalHttpsServer, location: str
) -> None:
    server.on("/go", Reply(status=302, headers={"Location": location}, body=""))
    with pytest.raises(ToolError, match="redirected somewhere not allowed"):
        await use("http.get", get("/go"))
    assert len(server.seen) == 1


async def test_redirect_chains_stop_after_three_hops(use: Any, server: LocalHttpsServer) -> None:
    for number in range(10):
        server.on(f"/{number}", Reply(status=302, headers={"Location": f"/{number + 1}"}, body=""))
    result = await use("http.get", get("/0"))
    assert result["status"] == 302 and result["redirects_followed"] == 3
    assert "not followed" in result["note"]
    assert len(server.seen) == 4


# ---------- http.request ----------


def post(path: str = "/items", **extra: Any) -> dict[str, Any]:
    return {"method": "POST", "url": f"https://{HOST}{path}", **extra}


async def test_post_sends_the_body_with_its_type_and_length(
    use: Any, server: LocalHttpsServer
) -> None:
    server.on("/items", Reply(status=201, body='{"id": 7}'))
    result = await use("http.request", post(body='{"name": "x"}'))
    assert result["status"] == 201 and result["ok"] is True
    (seen,) = server.seen
    assert (seen.method, seen.body) == ("POST", b'{"name": "x"}')
    assert seen.headers["content-type"] == "application/json"
    assert seen.headers["content-length"] == str(len(b'{"name": "x"}'))
    assert seen.headers["authorization"] == f"Bearer {SECRET}"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
async def test_each_write_method_is_sent_as_asked(
    use: Any, server: LocalHttpsServer, method: str
) -> None:
    server.on("/items", Reply(body="{}"))
    await use("http.request", post(method=method, body='{"a": 1}'))
    assert server.seen[0].method == method.upper()


async def test_a_request_without_a_body_says_so(use: Any, server: LocalHttpsServer) -> None:
    server.on("/items/5", Reply(status=200, body="{}"))
    await use("http.request", post("/items/5", method="DELETE"))
    (seen,) = server.seen
    assert seen.body == b"" and seen.headers["content-length"] == "0"


async def test_other_content_types_can_be_chosen(use: Any, server: LocalHttpsServer) -> None:
    server.on("/items", Reply(body="{}"))
    await use(
        "http.request", post(body="a=1&b=2", content_type="application/x-www-form-urlencoded")
    )
    assert server.seen[0].headers["content-type"] == "application/x-www-form-urlencoded"


@pytest.mark.parametrize(
    "arguments",
    [
        post(method="GET"),
        post(method="HEAD"),
        post(method="TRACE"),
        post(method="CONNECT"),
        post(method=""),
        post(body="{not json"),
        post(body="x" * (HUNDRED_KB + 1), content_type="text/plain"),
        post(body="é" * (HUNDRED_KB // 2 + 1), content_type="text/plain"),
        post(body={"a": 1}),
        post(body="{}", content_type="image/png"),
    ],
)
async def test_bad_requests_are_refused_before_sending(
    use: Any, server: LocalHttpsServer, arguments: dict[str, Any]
) -> None:
    with pytest.raises(ToolError):
        await use("http.request", arguments)
    assert server.seen == []


async def test_a_redirect_is_not_followed_for_a_write(use: Any, server: LocalHttpsServer) -> None:
    """An approved action runs exactly as the approver saw it: no hidden second request."""
    server.on("/items", Reply(status=307, headers={"Location": "https://other.example.com/x"}))
    result = await use("http.request", post(body='{"a": 1}'))
    assert result["status"] == 307 and result["redirects_followed"] == 0
    assert result["location"] == "https://other.example.com/x"
    assert "not followed" in result["note"]
    assert len(server.seen) == 1


def test_the_request_tool_only_accepts_write_methods_in_its_schema() -> None:
    from app.tools.base import ToolArgumentsError  # noqa: F401  (documented behaviour)

    schema = {
        "type": "object",
        "properties": {"method": {"type": "string", "enum": ["POST", "PUT", "PATCH", "DELETE"]}},
        "required": ["method"],
    }
    with pytest.raises(ToolError):
        validate_arguments(schema, {"method": "GET"})


# ---------- failures ----------


async def test_a_slow_server_times_out(
    use: Any, server: LocalHttpsServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http_tools, "TIMEOUT_SECONDS", 0.4)
    server.on("/slow", Reply(body="{}", delay=5))
    with pytest.raises(ToolError, match="took longer than"):
        await use("http.get", get("/slow"))


async def test_an_untrusted_certificate_is_refused(
    server: LocalHttpsServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client trusts the normal certificate authorities, not this test server's."""
    import ssl

    backend = SafeNetworkBackend(
        resolver=loopback, address_check=allow_everything, port_override=server.port
    )
    monkeypatch.setattr(
        http_tools,
        "new_fetcher",
        lambda: HttpFetcher(backend=backend, ssl_context=ssl.create_default_context()),
    )
    handler = get_handler("http.get")
    assert handler is not None
    context = ToolContext(
        org_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        integrations=FakeAccess(config()),
        tool_config={"integration_id": str(INTEGRATION_ID)},
    )
    with pytest.raises(ToolError, match="certificate"):
        await handler(get(), context)
    assert server.seen == []  # the handshake failed, so no request was ever sent


async def test_a_certificate_for_another_name_is_refused(
    use: Any, server: LocalHttpsServer
) -> None:
    """The name in the URL must match the certificate, whatever address we connected to."""
    # The test certificate does not cover this name, though the integration allows it.
    with pytest.raises(ToolError, match="certificate"):
        await use(
            "http.get",
            {"url": "https://unlisted.example.org/data"},
            cfg=config(allowed_hosts=["unlisted.example.org"]),
        )
    assert server.seen == []


async def test_an_unreachable_server_is_reported_plainly(
    server: LocalHttpsServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = SafeNetworkBackend(resolver=loopback, address_check=allow_everything, port_override=1)
    monkeypatch.setattr(
        http_tools,
        "new_fetcher",
        lambda: HttpFetcher(backend=backend, ssl_context=server.client_context()),
    )
    handler = get_handler("http.get")
    assert handler is not None
    context = ToolContext(
        org_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        integrations=FakeAccess(config()),
        tool_config={"integration_id": str(INTEGRATION_ID)},
    )
    with pytest.raises(ToolError, match="Could not connect"):
        await handler(get(), context)


async def test_without_integration_access_the_tool_says_so() -> None:
    handler = get_handler("http.get")
    assert handler is not None
    context = ToolContext(org_id=uuid.uuid4(), agent_id=uuid.uuid4(), run_id=uuid.uuid4())
    with pytest.raises(ToolError, match="not connected to an integration"):
        await handler(get(), context)


# ---------- the real address check is on by default ----------


@pytest.fixture
def strict(server: LocalHttpsServer, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A fetcher with the production address check, where the host's DNS answer is chosen."""

    def install(*addresses: str) -> None:
        async def resolver(host: str, port: int) -> list[str]:
            return list(addresses)

        backend = SafeNetworkBackend(resolver=resolver, port_override=server.port)
        monkeypatch.setattr(
            http_tools,
            "new_fetcher",
            lambda: HttpFetcher(backend=backend, ssl_context=server.client_context()),
        )

    return install


@pytest.mark.parametrize(
    "answer",
    [
        ["127.0.0.1"],
        ["10.0.0.7"],
        ["169.254.169.254"],
        ["::1"],
        ["8.8.8.8", "127.0.0.1"],
        ["::ffff:7f00:1"],
    ],
)
async def test_an_allowed_host_that_points_inside_is_still_refused(
    strict: Any, server: LocalHttpsServer, answer: list[str]
) -> None:
    """The admin listed the name, but the platform checks where it really goes (SSRF)."""
    strict(*answer)
    handler = get_handler("http.get")
    assert handler is not None
    context = ToolContext(
        org_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        integrations=FakeAccess(config()),
        tool_config={"integration_id": str(INTEGRATION_ID)},
    )
    with pytest.raises(ToolError, match="public internet address"):
        await handler(get(), context)
    assert server.seen == []


async def test_a_host_that_does_not_resolve_is_reported(
    server: LocalHttpsServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.netsafety import HostResolutionError

    async def nothing(host: str, port: int) -> list[str]:
        raise HostResolutionError(host)

    backend = SafeNetworkBackend(resolver=nothing)
    monkeypatch.setattr(http_tools, "new_fetcher", lambda: HttpFetcher(backend=backend))
    handler = get_handler("http.get")
    assert handler is not None
    context = ToolContext(
        org_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        integrations=FakeAccess(config()),
        tool_config={"integration_id": str(INTEGRATION_ID)},
    )
    with pytest.raises(ToolError, match="could not be found"):
        await handler(get(), context)
