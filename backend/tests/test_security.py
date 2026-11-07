import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.errors import ApiError
from app.core.security import TokenVerifier
from tests.auth_helpers import AUDIENCE, ISSUER, StaticKeys, make_token, new_key


@pytest.fixture(scope="module")
def key() -> ec.EllipticCurvePrivateKey:
    return new_key()


@pytest.fixture
def verifier(key: ec.EllipticCurvePrivateKey) -> TokenVerifier:
    return TokenVerifier(StaticKeys(key), issuer=ISSUER, audience=AUDIENCE)


def _rejected(verifier: TokenVerifier, token: str, status: int = 401) -> ApiError:
    with pytest.raises(ApiError) as caught:
        verifier.verify(token)
    assert caught.value.status_code == status
    return caught.value


def test_valid_token_yields_claims(
    verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey
) -> None:
    user_id = uuid.uuid4()
    claims = verifier.verify(make_token(key, user_id=user_id, email="Ada@Example.com"))
    assert claims.user_id == user_id
    assert claims.email == "ada@example.com"  # normalized to lower case


def test_expired_token_is_rejected(
    verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey
) -> None:
    error = _rejected(verifier, make_token(key, expires_in=-120))
    assert error.code == "invalid_token"


def test_token_signed_by_another_key_is_rejected(verifier: TokenVerifier) -> None:
    _rejected(verifier, make_token(new_key()))


def test_wrong_audience_is_rejected(
    verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey
) -> None:
    _rejected(verifier, make_token(key, audience="somebody-else"))


def test_wrong_issuer_is_rejected(verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey) -> None:
    _rejected(verifier, make_token(key, issuer="https://evil.example.com/auth/v1"))


@pytest.mark.parametrize("claim", ["sub", "exp", "aud", "iss"])
def test_missing_required_claim_is_rejected(
    verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey, claim: str
) -> None:
    _rejected(verifier, make_token(key, omit=(claim,)))


def test_token_without_email_is_rejected(
    verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey
) -> None:
    _rejected(verifier, make_token(key, email=None))


def test_non_uuid_subject_is_rejected(
    verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey
) -> None:
    _rejected(verifier, make_token(key, sub="not-a-uuid"))


def test_anonymous_user_is_rejected(
    verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey
) -> None:
    _rejected(verifier, make_token(key, is_anonymous=True))


def test_non_authenticated_role_is_rejected(
    verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey
) -> None:
    _rejected(verifier, make_token(key, role="anon"))


def test_hs256_token_is_rejected(verifier: TokenVerifier) -> None:
    """Algorithm-confusion attack: a symmetric token must never be accepted."""
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iss": ISSUER, "aud": AUDIENCE, "exp": 9999999999},
        "a-shared-secret-of-sufficient-length-1234",
        algorithm="HS256",
    )
    _rejected(verifier, token)


def test_alg_none_token_is_rejected(verifier: TokenVerifier) -> None:
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iss": ISSUER, "aud": AUDIENCE, "exp": 9999999999},
        None,  # type: ignore[arg-type]
        algorithm="none",
    )
    _rejected(verifier, token)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer x"])
def test_garbage_is_rejected(verifier: TokenVerifier, garbage: str) -> None:
    _rejected(verifier, garbage)


def test_rejection_does_not_leak_the_reason(
    verifier: TokenVerifier, key: ec.EllipticCurvePrivateKey
) -> None:
    error = _rejected(verifier, make_token(key, audience="x"))
    assert "audience" not in error.message.lower()


def test_unreachable_key_server_is_a_503_not_a_401(key: ec.EllipticCurvePrivateKey) -> None:
    class Down:
        def get_signing_key_from_jwt(self, token: str) -> None:
            raise jwt.PyJWKClientConnectionError("connection refused")

    verifier = TokenVerifier(Down(), issuer=ISSUER, audience=AUDIENCE)  # type: ignore[arg-type]
    error = _rejected(verifier, make_token(key), status=503)
    assert error.code == "auth_unavailable"
