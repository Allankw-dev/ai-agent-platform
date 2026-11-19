"""Network safety for tools that call outside servers.

An agent chooses the URL, so every request is treated as hostile until proven otherwise:

* The URL must be https, on the default port, without credentials in it.
* The host must be one an admin listed (checked by the caller against the integration).
* The host is resolved by *us*, and every address it resolves to must be a public one. The check
  is made on the very addresses we then connect to (`SafeNetworkBackend`), so a DNS answer that
  changes between a check and a connection (DNS rebinding) cannot reach an internal address.
* TLS is verified against the host name from the URL, not the address we connected to.

Refused addresses: loopback, private ranges, link-local (including the cloud metadata address
169.254.169.254), shared/CGNAT space, multicast, reserved, unspecified, IPv6 unique-local, and
IPv6 forms that carry an IPv4 address (IPv4-mapped, 6to4, Teredo, NAT64).
"""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from httpcore import AnyIOBackend, AsyncNetworkBackend, AsyncNetworkStream, ConnectError

from app.tools.base import ToolError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
# The exact option type httpcore's backend interface uses.
SocketOption = (
    tuple[int, int, int] | tuple[int, int, bytes | bytearray] | tuple[int, int, None, int]
)

HTTPS_PORT = 443
MAX_URL_CHARS = 2_000
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)

_EXTRA_BLOCKED = tuple(
    ipaddress.ip_network(net)
    for net in (
        "100.64.0.0/10",  # shared address space (CGNAT)
        "192.0.0.0/24",  # IETF protocol assignments
        "192.88.99.0/24",  # old 6to4 relay
        "198.18.0.0/15",  # benchmarking
        "240.0.0.0/4",  # reserved
        "64:ff9b::/96",  # NAT64
        "64:ff9b:1::/48",  # local-use NAT64
        "2001::/32",  # Teredo
        "2002::/16",  # 6to4
        "fc00::/7",  # unique local
        "fe80::/10",  # link-local
        "::ffff:0:0/96",  # IPv4-mapped
    )
)


class AddressNotAllowedError(Exception):
    """The host resolves to an address that must not be called."""


class HostResolutionError(Exception):
    """The host name did not resolve."""


def is_public_address(address: IPAddress) -> bool:
    """True only for an address on the public internet."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return False  # never trust a v4 address wearing a v6 costume
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    ):
        return False
    return not any(
        address in network for network in _EXTRA_BLOCKED if network.version == address.version
    )


def check_addresses(addresses: Sequence[str]) -> list[IPAddress]:
    """Parse resolved addresses; raise unless there is at least one and *all* are public."""
    parsed: list[IPAddress] = []
    for raw in addresses:
        try:
            parsed.append(ipaddress.ip_address(raw.split("%", 1)[0]))
        except ValueError as exc:
            raise AddressNotAllowedError("unparseable address") from exc
    if not parsed:
        raise AddressNotAllowedError("no addresses")
    if not all(is_public_address(address) for address in parsed):
        raise AddressNotAllowedError("not a public address")
    return parsed


Resolver = Callable[[str, int], Awaitable[list[str]]]
AddressCheck = Callable[[Sequence[str]], list[IPAddress]]


async def system_resolver(host: str, port: int) -> list[str]:
    """Resolve with the operating system's resolver, returning each distinct address once."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HostResolutionError(host) from exc
    seen: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in seen:
            seen.append(address)
    return seen


class SafeNetworkBackend(AsyncNetworkBackend):
    """Resolves the host, refuses non-public addresses, then connects to a checked address.

    httpcore still performs TLS with the original host name, so certificates are verified for the
    site the URL names. `port_override` and `address_check` exist only so tests can point at a
    local server; production uses the defaults.
    """

    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        address_check: AddressCheck = check_addresses,
        delegate: AsyncNetworkBackend | None = None,
        port_override: int | None = None,
    ) -> None:
        self._resolver = resolver
        self._address_check = address_check
        self._delegate = delegate or AnyIOBackend()
        self._port_override = port_override

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (signature set by httpcore)
        local_address: str | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> AsyncNetworkStream:
        addresses = self._address_check(await self._resolver(host, port))
        target_port = self._port_override or port
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._delegate.connect_tcp(
                    str(address),
                    target_port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except ConnectError as exc:  # try the next checked address
                last_error = exc
        raise last_error or ConnectError("no address could be reached")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 (signature set by httpcore)
        socket_options: Iterable[SocketOption] | None = None,
    ) -> AsyncNetworkStream:
        raise ConnectError("Unix sockets are not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


@dataclass(frozen=True)
class SafeUrl:
    host: str
    path_and_query: str

    @property
    def url(self) -> str:
        return f"https://{self.host}{self.path_and_query}"


def parse_https_url(raw: object) -> SafeUrl:
    """Validate a URL chosen by a model. Raises ToolError with a message safe to show."""
    if not isinstance(raw, str) or not raw.strip():
        raise ToolError("Give a full https:// URL.")
    text = raw.strip()
    if len(text) > MAX_URL_CHARS:
        raise ToolError(f"The URL is longer than {MAX_URL_CHARS} characters.")
    if (
        not text.isascii()
        or any(ord(char) < 0x21 or ord(char) == 0x7F for char in text)
        or "\\" in text
    ):
        raise ToolError(
            "The URL contains spaces, control or non-ASCII characters. Percent-encode them."
        )
    try:
        parts = urlsplit(text)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise ToolError("That is not a valid URL.") from None
    if parts.scheme.lower() != "https":
        raise ToolError("Only https:// URLs are allowed.")
    if "@" in parts.netloc:
        raise ToolError("URLs with a user name or password in them are not allowed.")
    if port not in (None, HTTPS_PORT):
        raise ToolError("Only the standard https port (443) is allowed.")
    host = (host or "").rstrip(".")
    if not _HOSTNAME.match(host):
        raise ToolError("The URL needs a host name such as api.example.com (not an IP address).")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ToolError("The URL needs a host name, not an IP address.")
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return SafeUrl(host=host, path_and_query=f"{path}{query}")
