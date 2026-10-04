import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError

from app.core.auth import (
    AuthenticationServiceUnavailable,
    AuthenticatedOperator,
    InvalidAuthenticationCredentials,
    SupabaseJWTVerifier,
    get_supabase_jwt_verifier,
    require_authenticated_operator,
)

ISSUER = "https://example-project.supabase.co/auth/v1"
AUDIENCE = "tracework-test"
KID = "test-signing-key"
PRIVATE_KEY = ec.derive_private_key(123456789, ec.SECP256R1())
PUBLIC_KEY = PRIVATE_KEY.public_key()
OTHER_PRIVATE_KEY = ec.derive_private_key(987654321, ec.SECP256R1())


class StaticJWKClient:
    def __init__(self, key=PUBLIC_KEY) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, token: str):
        return SimpleNamespace(key=self.key)


def _token(
    *,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_delta: timedelta = timedelta(minutes=5),
    key=PRIVATE_KEY,
    kid: str = KID,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "aud": audience,
            "email": "Operator@Example.Test",
            "exp": now + expires_delta,
            "iat": now - timedelta(seconds=1),
            "is_anonymous": False,
            "iss": issuer,
            "sub": "stable-user-id",
        },
        key,
        algorithm="ES256",
        headers={"kid": kid},
    )


def _verifier(*, audience: str = AUDIENCE, client=None) -> SupabaseJWTVerifier:
    return SupabaseJWTVerifier(
        issuer=ISSUER,
        audience=audience,
        jwks_client=client or StaticJWKClient(),
    )


def test_valid_token_returns_only_authenticated_operator_fields() -> None:
    operator = _verifier().verify(_token())

    assert operator == AuthenticatedOperator(
        subject="stable-user-id",
        email="operator@example.test",
    )
    assert set(operator.model_dump()) == {"subject", "email"}


@pytest.mark.parametrize(
    ("token", "verifier"),
    [
        (_token(key=OTHER_PRIVATE_KEY), _verifier()),
        (_token(expires_delta=timedelta(seconds=-1)), _verifier()),
        (_token(issuer="https://other.supabase.co/auth/v1"), _verifier()),
        (_token(audience="wrong-audience"), _verifier()),
    ],
)
def test_invalid_signature_expiry_issuer_and_audience_are_rejected(
    token,
    verifier,
) -> None:
    with pytest.raises(InvalidAuthenticationCredentials):
        verifier.verify(token)


def test_expected_audience_is_configuration_driven() -> None:
    configured_audience = "custom-tracework-audience"

    operator = _verifier(audience=configured_audience).verify(
        _token(audience=configured_audience)
    )

    assert operator.subject == "stable-user-id"


def test_cached_known_key_verifies_locally_without_another_fetch() -> None:
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(PUBLIC_KEY, as_dict=True)
    jwk.update({"alg": "ES256", "kid": KID, "use": "sig"})
    client = PyJWKClient(
        f"{ISSUER}/.well-known/jwks.json",
        lifespan=600,
        cooldown_duration=0,
    )
    client.fetch_data = Mock(return_value={"keys": [jwk]})
    verifier = _verifier(client=client)
    token = _token()

    verifier.verify(token)
    client.fetch_data.side_effect = PyJWKClientConnectionError(
        "test JWKS unavailable"
    )
    verifier.verify(token)

    client.fetch_data.assert_called_once_with()


def test_unknown_key_refreshes_jwks_and_then_verifies() -> None:
    old_private_key = ec.derive_private_key(111111111, ec.SECP256R1())
    old_jwk = jwt.algorithms.ECAlgorithm.to_jwk(
        old_private_key.public_key(), as_dict=True
    )
    old_jwk.update({"alg": "ES256", "kid": "old-key", "use": "sig"})
    new_jwk = jwt.algorithms.ECAlgorithm.to_jwk(PUBLIC_KEY, as_dict=True)
    new_jwk.update({"alg": "ES256", "kid": KID, "use": "sig"})
    client = PyJWKClient(
        f"{ISSUER}/.well-known/jwks.json",
        lifespan=600,
        cooldown_duration=0,
    )
    client.fetch_data = Mock(
        side_effect=[{"keys": [old_jwk]}, {"keys": [old_jwk, new_jwk]}]
    )

    operator = _verifier(client=client).verify(_token())

    assert operator.subject == "stable-user-id"
    assert client.fetch_data.call_count == 2


def test_jwks_failure_is_unavailable_only_without_a_usable_cached_key() -> None:
    client = PyJWKClient(
        f"{ISSUER}/.well-known/jwks.json",
        lifespan=600,
        cooldown_duration=0,
    )
    client.fetch_data = Mock(
        side_effect=PyJWKClientConnectionError("test JWKS unavailable")
    )

    with pytest.raises(AuthenticationServiceUnavailable):
        _verifier(client=client).verify(_token())


def test_dependency_has_small_sanitized_http_errors() -> None:
    app = FastAPI()

    @app.get("/protected")
    def protected(
        operator: AuthenticatedOperator = Depends(
            require_authenticated_operator
        ),
    ):
        return operator

    app.dependency_overrides[get_supabase_jwt_verifier] = lambda: _verifier()

    async def requests():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return (
                await client.get("/protected"),
                await client.get(
                    "/protected", headers={"Authorization": "Basic value"}
                ),
                await client.get(
                    "/protected",
                    headers={"Authorization": f"Bearer {_token()}"},
                ),
            )

    missing, malformed, valid = asyncio.run(requests())

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert valid.status_code == 200
    assert valid.json() == {
        "subject": "stable-user-id",
        "email": "operator@example.test",
    }
    combined_errors = missing.text + malformed.text
    assert "eyJ" not in combined_errors
    assert "signing" not in combined_errors.lower()


def test_dependency_maps_jwks_outage_to_sanitized_503() -> None:
    app = FastAPI()

    class UnavailableVerifier:
        def verify(self, token: str):
            raise AuthenticationServiceUnavailable

    @app.get("/protected")
    def protected(
        operator: AuthenticatedOperator = Depends(
            require_authenticated_operator
        ),
    ):
        return operator

    app.dependency_overrides[get_supabase_jwt_verifier] = UnavailableVerifier

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(
                "/protected",
                headers={"Authorization": f"Bearer {_token()}"},
            )

    response = asyncio.run(request())

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Authentication verification is temporarily unavailable"
    }
    assert "eyJ" not in response.text
