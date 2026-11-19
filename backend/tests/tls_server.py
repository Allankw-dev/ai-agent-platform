"""A tiny local HTTPS server, so the HTTP tools can be tested for real without the internet.

It serves a certificate valid for a few made-up host names. A test points the tool's network
backend at it (resolving those names to 127.0.0.1 and the port to this server's) and trusts only
this certificate, so TLS verification still runs exactly as in production.
"""

import asyncio
import datetime
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

if TYPE_CHECKING:
    from app.tools.http import HttpFetcher

HOSTS = ("api.example.com", "other.example.com", "evil.example.net")


@dataclass
class Seen:
    """One request the server received."""

    method: str
    target: str
    headers: dict[str, str]
    body: bytes

    @property
    def host(self) -> str:
        return self.headers.get("host", "")


@dataclass
class Reply:
    status: int = 200
    body: bytes | str = b""
    content_type: str | None = "application/json"
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0


Route = Reply | Callable[[Seen], Reply]


def make_certificate(hosts: tuple[str, ...] = HOSTS) -> tuple[bytes, bytes]:
    """A self-signed certificate (acting as its own authority) for `hosts`. Returns (cert, key)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(h) for h in hosts]), critical=False
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return (
        certificate.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


class LocalHttpsServer:
    def __init__(self, directory: Path) -> None:
        self.routes: dict[str, Route] = {}
        self.seen: list[Seen] = []
        self.port = 0
        self._cert_pem, key_pem = make_certificate()
        cert_file, key_file = directory / "cert.pem", directory / "key.pem"
        cert_file.write_bytes(self._cert_pem)
        key_file.write_bytes(key_pem)
        self._server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._server_context.load_cert_chain(cert_file, key_file)
        self._server: asyncio.Server | None = None

    def client_context(self) -> ssl.SSLContext:
        """A client context that trusts only this server's certificate (and checks host names)."""
        return ssl.create_default_context(cadata=self._cert_pem.decode("ascii"))

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, "127.0.0.1", 0, ssl=self._server_context
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def on(self, path: str, reply: Route) -> None:
        self.routes[path] = reply

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(length) if length else b""
            seen = Seen(method=method, target=target, headers=headers, body=body)
            self.seen.append(seen)

            route = self.routes.get(target.split("?", 1)[0], Reply(status=404, body=b"not found"))
            reply = route(seen) if callable(route) else route
            if reply.delay:
                await asyncio.sleep(reply.delay)
            payload = reply.body.encode("utf-8") if isinstance(reply.body, str) else reply.body
            out = [f"HTTP/1.1 {reply.status} X"]
            if reply.content_type is not None:
                out.append(f"Content-Type: {reply.content_type}")
            out += [f"{key}: {value}" for key, value in reply.headers.items()]
            out += [f"Content-Length: {len(payload)}", "Connection: close", "", ""]
            writer.write("\r\n".join(out).encode("latin-1") + payload)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError, OSError):
            pass  # a client that hung up or failed the handshake is part of some tests
        finally:
            writer.close()


def local_fetcher(server: LocalHttpsServer) -> "HttpFetcher":
    """A tool fetcher wired to `server`: the made-up host names resolve to this machine, TLS is
    verified against the server's own certificate, and nothing else is trusted."""
    import ipaddress

    from app.tools.http import HttpFetcher
    from app.tools.netsafety import SafeNetworkBackend

    async def loopback(host: str, port: int) -> list[str]:
        return ["127.0.0.1"]

    backend = SafeNetworkBackend(
        resolver=loopback,
        address_check=lambda addresses: [ipaddress.ip_address(a) for a in addresses],
        port_override=server.port,
    )
    return HttpFetcher(backend=backend, ssl_context=server.client_context())
