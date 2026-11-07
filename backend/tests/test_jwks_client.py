"""Verify tokens through the real PyJWKClient against a local JWKS server."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.errors import ApiError
from app.core.security import TokenVerifier
from tests.auth_helpers import AUDIENCE, jwks_for, make_token, new_key

JWKS_PATH = "/auth/v1/.well-known/jwks.json"


@pytest.fixture
def signing_key() -> ec.EllipticCurvePrivateKey:
    return new_key()


@pytest.fixture
def jwks_server(
    signing_key: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    body = json.dumps(jwks_for(signing_key)).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status = 200 if self.path == JWKS_PATH else 404
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body if status == 200 else b"{}")

        def log_message(self, format: str, *args: Any) -> None:
            return

    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/auth/v1"
    finally:
        server.shutdown()
        server.server_close()


def _verifier(issuer: str) -> TokenVerifier:
    keys = jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True, timeout=2)
    return TokenVerifier(keys, issuer=issuer, audience=AUDIENCE)


def test_token_verifies_against_a_real_jwks_endpoint(
    jwks_server: str, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    verifier = _verifier(jwks_server)
    claims = verifier.verify(make_token(signing_key, issuer=jwks_server))
    assert claims.email == "ada@example.com"


def test_unknown_key_id_is_rejected(
    jwks_server: str, signing_key: ec.EllipticCurvePrivateKey
) -> None:
    verifier = _verifier(jwks_server)
    with pytest.raises(ApiError) as caught:
        verifier.verify(make_token(signing_key, issuer=jwks_server, kid="rotated-away"))
    assert caught.value.status_code == 401


def test_unreachable_jwks_endpoint_gives_503(signing_key: ec.EllipticCurvePrivateKey) -> None:
    issuer = "http://127.0.0.1:9/auth/v1"  # nothing listens on port 9
    verifier = _verifier(issuer)
    with pytest.raises(ApiError) as caught:
        verifier.verify(make_token(signing_key, issuer=issuer))
    assert caught.value.status_code == 503
