"""Service-token authentication for provider-initiated calls.

The voice agent and messaging providers call our backend's AI tool endpoints.
They authenticate with a *clinic-scoped* service token so that:

* the provider can never pick an arbitrary tenant -- the token already
  encodes the tenant, and the tenant is re-derived from the token on every
  request (PRD 8.2);
* tokens can be rotated and revoked per clinic;
* service tokens cannot be used for staff operations (they are not staff
  credentials and carry no human role).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from rest_framework import authentication, exceptions

from apps.core.constants import ConnectionStatus


def hash_token(raw_token: str) -> str:
    """Hash a service token for storage (tokens are never stored in plaintext)."""
    from django.conf import settings

    pepper = getattr(settings, "INTERNAL_SERVICE_TOKEN_PEPPER", "")
    return hashlib.sha256(f"{pepper}:{raw_token}".encode()).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(40)


def token_matches(raw_token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_token(raw_token), stored_hash)


def looks_like_jwt(raw_token: str) -> bool:
    """Is this bearer credential a JSON Web Token?

    A JWT is three dot-separated base64url segments. Service tokens are
    generated with ``secrets.token_urlsafe``, whose alphabet contains no
    dots, so the two can be told apart without guessing.
    """
    return raw_token.count(".") == 2


class ServiceTokenPrincipal:
    """Auth principal for provider calls.

    Exposes just enough for permission classes: the clinic it belongs to and
    the set of tool names it may invoke.
    """

    is_authenticated = True
    is_anonymous = False
    is_active = True
    is_staff = False
    is_superuser = False
    is_platform_admin = False
    role = "service_token"
    pk = None
    id = None

    def __init__(self, service_token) -> None:  # noqa: ANN001
        self.service_token = service_token
        self.clinic = service_token.clinic
        self.clinic_id = service_token.clinic_id
        self.scopes = list(service_token.scopes or [])

    @property
    def username(self) -> str:
        return f"service:{self.clinic_id}"

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"ServiceTokenPrincipal(clinic={self.clinic})"


class ClinicServiceTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):  # noqa: ANN001
        from apps.accounts.models import ClinicServiceToken

        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Invalid Authorization header.")

        raw_token = header[1].decode()

        if looks_like_jwt(raw_token):
            # This is a staff JWT. Step aside and let the JWT authenticator
            # handle it, so a malformed or expired token produces the right
            # error instead of "invalid service token".
            return None

        # The stored hash is a unique, indexed column, so this is a single
        # lookup rather than a scan over every token in the system.
        token = (
            ClinicServiceToken.objects.select_related("clinic")
            .filter(token_hash=hash_token(raw_token))
            .first()
        )
        if token is None:
            raise exceptions.AuthenticationFailed("Invalid service token.")
        if token.revoked_at is not None:
            raise exceptions.AuthenticationFailed("Service token revoked.")
        if token.expires_at is not None and token.expires_at <= timezone_now():
            raise exceptions.AuthenticationFailed("Service token expired.")
        principal = ServiceTokenPrincipal(token)
        return principal, token


def timezone_now():
    from django.utils import timezone

    return timezone.now()
