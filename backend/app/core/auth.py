from functools import lru_cache
from typing import Protocol

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.core.config import get_settings

SUPPORTED_SUPABASE_JWT_ALGORITHMS = ("ES256", "RS256")
JWKS_CACHE_LIFETIME_SECONDS = 600


class AuthenticatedOperator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str
    email: str | None = None

    @field_validator("subject")
    @classmethod
    def reject_blank_subject(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("authenticated subject must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        return value or None


class InvalidAuthenticationCredentials(RuntimeError):
    pass


class AuthenticationServiceUnavailable(RuntimeError):
    pass


class JWKClient(Protocol):
    def get_signing_key_from_jwt(self, token: str): ...


class SupabaseJWTVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_client: JWKClient | None = None,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks_client = jwks_client or PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=JWKS_CACHE_LIFETIME_SECONDS,
            cache_keys=False,
            timeout=5,
            cooldown_duration=0,
        )

    def verify(self, token: str) -> AuthenticatedOperator:
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") not in SUPPORTED_SUPABASE_JWT_ALGORITHMS
                or not isinstance(header.get("kid"), str)
                or not header["kid"].strip()
            ):
                raise InvalidAuthenticationCredentials
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(SUPPORTED_SUPABASE_JWT_ALGORITHMS),
                audience=self.audience,
                issuer=self.issuer,
                options={
                    "require": [
                        "aud",
                        "exp",
                        "iat",
                        "iss",
                        "is_anonymous",
                        "sub",
                    ]
                },
            )
            if claims["is_anonymous"] is not False:
                raise InvalidAuthenticationCredentials
            email = claims.get("email")
            if email is not None and not isinstance(email, str):
                raise InvalidAuthenticationCredentials
            return AuthenticatedOperator(
                subject=claims["sub"],
                email=email,
            )
        except PyJWKClientConnectionError as exc:
            raise AuthenticationServiceUnavailable from exc
        except AuthenticationServiceUnavailable:
            raise
        except (
            InvalidAuthenticationCredentials,
            InvalidTokenError,
            PyJWKClientError,
            ValidationError,
            KeyError,
            TypeError,
        ) as exc:
            raise InvalidAuthenticationCredentials from exc


@lru_cache
def get_supabase_jwt_verifier() -> SupabaseJWTVerifier:
    settings = get_settings()
    if settings.supabase_auth_issuer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication verification is temporarily unavailable",
        )
    return SupabaseJWTVerifier(
        issuer=settings.supabase_auth_issuer,
        audience=settings.supabase_auth_audience,
    )


bearer_scheme = HTTPBearer(auto_error=False)


def require_authenticated_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: SupabaseJWTVerifier = Depends(get_supabase_jwt_verifier),
) -> AuthenticatedOperator:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_error("Authentication credentials are required")
    try:
        return verifier.verify(credentials.credentials)
    except InvalidAuthenticationCredentials as exc:
        raise _authentication_error(
            "Invalid or expired authentication credentials"
        ) from exc
    except AuthenticationServiceUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication verification is temporarily unavailable",
        ) from exc


def _authentication_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
