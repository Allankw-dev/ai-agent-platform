"""Address and URL rules for tools that call outside servers (SSRF protection)."""

import ipaddress
from collections.abc import Sequence
from typing import Any

import httpcore
import pytest

from app.tools.base import ToolError
from app.tools.netsafety import (
    AddressNotAllowedError,
    SafeNetworkBackend,
    check_addresses,
    is_public_address,
    parse_https_url,
)

PUBLIC = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111", "2001:4860:4860::8888"]
NOT_PUBLIC = [
    "127.0.0.1",
    "127.1.2.3",
    "10.0.0.1",
    "172.16.5.4",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata
    "169.254.1.1",
    "100.64.0.1",  # shared / CGNAT
    "100.127.255.254",
    "0.0.0.0",  # noqa: S104
    "224.0.0.1",
    "239.255.255.250",
    "240.0.0.1",
    "255.255.255.255",
    "198.18.0.1",
    "192.0.0.8",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "fd12:3456::1",
    "ff02::1",
    "::ffff:127.0.0.1",  # IPv4-mapped IPv6
    "::ffff:10.0.0.1",
    "::ffff:8.8.8.8",  # even a public v4 address wearing a v6 costume
    "64:ff9b::7f00:1",  # NAT64 pointing at 127.0.0.1
    "2002:7f00:1::1",  # 6to4 pointing at 127.0.0.1
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
]


@pytest.mark.parametrize("address", PUBLIC)
def test_public_addresses_are_allowed(address: str) -> None:
    assert is_public_address(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize("address", NOT_PUBLIC)
def test_internal_addresses_are_refused(address: str) -> None:
    assert is_public_address(ipaddress.ip_address(address)) is False


def test_every_resolved_address_must_be_public() -> None:
    assert [str(a) for a in check_addresses(["8.8.8.8", "1.1.1.1"])] == ["8.8.8.8", "1.1.1.1"]
    with pytest.raises(AddressNotAllowedError):
        check_addresses(["8.8.8.8", "10.0.0.5"])  # one bad address spoils the host
    with pytest.raises(AddressNotAllowedError):
        check_addresses(["8.8.8.8", "::1"])
    with pytest.raises(AddressNotAllowedError):
        check_addresses([])
    with pytest.raises(AddressNotAllowedError):
        check_addresses(["not-an-address"])


def test_an_ipv6_scope_id_is_ignored_when_checking() -> None:
    with pytest.raises(AddressNotAllowedError):
        check_addresses(["fe80::1%eth0"])


# ---------- URLs ----------


def test_a_plain_https_url_is_accepted() -> None:
    url = parse_https_url("https://API.Example.com/v1/items?id=5&x=y")
    assert (url.host, url.path_and_query) == ("api.example.com", "/v1/items?id=5&x=y")
    assert url.url == "https://api.example.com/v1/items?id=5&x=y"


def test_a_bare_host_gets_a_root_path_and_the_default_port_is_fine() -> None:
    assert parse_https_url("https://api.example.com").path_and_query == "/"
    assert parse_https_url("https://api.example.com:443/x").host == "api.example.com"
    assert parse_https_url("  https://api.example.com/x  ").path_and_query == "/x"
    assert parse_https_url("https://api.example.com./x").host == "api.example.com"


@pytest.mark.parametrize(
    "bad",
    [
        "http://api.example.com/",
        "ftp://api.example.com/",
        "file:///etc/passwd",
        "gopher://api.example.com/",
        "javascript:alert(1)",
        "//api.example.com/",
        "api.example.com/path",
        "https://api.example.com:8443/",
        "https://api.example.com:80/",
        "https://user:pass@api.example.com/",
        "https://api.example.com@evil.example.net/",
        "https://evil.example.net\\@api.example.com/",
        "https://127.0.0.1/",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://0x7f000001/",
        "https://2130706433/",
        "https://localhost/",
        "https://intranet/",
        "https://exa mple.com/",
        "https://api.example.com/a b",
        "https://api.example.com/\nHost: evil",
        "https://api.example.com/\x00",
        "https://bücher.example.com/",
        "https://api.example.com/é",
        "https://-bad.example.com/",
        "https://",
        "",
        "   ",
        "https://" + "a" * 70 + ".example.com/",
        "https://api.example.com/" + "a" * 2_100,
    ],
)
def test_bad_urls_are_refused(bad: str) -> None:
    with pytest.raises(ToolError):
        parse_https_url(bad)


@pytest.mark.parametrize("not_text", [None, 5, ["https://api.example.com"], {"url": "x"}])
def test_a_url_must_be_text(not_text: Any) -> None:
    with pytest.raises(ToolError):
        parse_https_url(not_text)


# ---------- the backend ----------


class RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, fail: Sequence[str] = ()) -> None:
        self.connected: list[tuple[str, int]] = []
        self._fail = set(fail)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        self.connected.append((host, port))
        if host in self._fail:
            raise httpcore.ConnectError("refused")
        return object()  # type: ignore[return-value]

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise AssertionError("not used")

    async def sleep(self, seconds: float) -> None:
        return None


def resolving(*addresses: str) -> Any:
    calls: list[tuple[str, int]] = []

    async def resolver(host: str, port: int) -> list[str]:
        calls.append((host, port))
        return list(addresses)

    resolver.calls = calls  # type: ignore[attr-defined]
    return resolver


async def test_it_connects_to_the_checked_address_not_the_name() -> None:
    delegate, resolver = RecordingBackend(), resolving("93.184.216.34")
    backend = SafeNetworkBackend(resolver=resolver, delegate=delegate)
    await backend.connect_tcp("api.example.com", 443)
    assert delegate.connected == [("93.184.216.34", 443)]  # an address, so no second lookup
    assert resolver.calls == [("api.example.com", 443)]  # resolved exactly once


@pytest.mark.parametrize(
    "answer",
    [["127.0.0.1"], ["10.1.2.3"], ["169.254.169.254"], ["8.8.8.8", "192.168.0.9"], ["::1"], []],
)
async def test_a_host_resolving_to_an_internal_address_is_never_connected(
    answer: list[str],
) -> None:
    delegate = RecordingBackend()
    backend = SafeNetworkBackend(resolver=resolving(*answer), delegate=delegate)
    with pytest.raises(AddressNotAllowedError):
        await backend.connect_tcp("api.example.com", 443)
    assert delegate.connected == []  # not even an attempt


async def test_it_tries_the_next_checked_address_when_one_is_down() -> None:
    delegate = RecordingBackend(fail=["8.8.8.8"])
    backend = SafeNetworkBackend(resolver=resolving("8.8.8.8", "1.1.1.1"), delegate=delegate)
    await backend.connect_tcp("api.example.com", 443)
    assert [host for host, _ in delegate.connected] == ["8.8.8.8", "1.1.1.1"]


async def test_unix_sockets_are_never_allowed() -> None:
    with pytest.raises(httpcore.ConnectError):
        await SafeNetworkBackend().connect_unix_socket("/var/run/docker.sock")
