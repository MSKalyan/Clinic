"""Provider abstraction.

The domain layer never talks to a provider's proprietary format. Each
adapter converts a provider's payload into internal :class:`ProviderEvent`
objects and keeps the original provider event id so that duplicate and
out-of-order deliveries can be detected (PRD 7.3).
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderEvent:
    """A normalised provider event."""

    provider_type: str
    provider_event_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: Trusted routing hint (e.g. the dialed number) used to find the clinic.
    clinic_hint: str | None = None
    occurred_at: datetime | None = None


class ProviderError(Exception):
    """Raised when a provider call fails."""


@runtime_checkable
class VoiceProvider(Protocol):
    """Managed voice agent platform (e.g. Sarvam Voice Agents)."""

    provider_type: str

    def verify_webhook(self, request) -> bool: ...

    def parse_events(self, payload: dict[str, Any]) -> list[ProviderEvent]: ...


@runtime_checkable
class MessagingProvider(Protocol):
    """Business messaging platform (e.g. WhatsApp Cloud API)."""

    provider_type: str
    channel: str

    def verify_webhook(self, request) -> bool: ...

    def parse_events(self, payload: dict[str, Any]) -> list[ProviderEvent]: ...

    def send_message(
        self,
        *,
        clinic,
        recipient_phone: str,
        template_id: str,
        body: str = "",
        appointment=None,
        payload: dict[str, Any] | None = None,
    ) -> str: ...


@runtime_checkable
class TelephonyProvider(Protocol):
    """PSTN provider (call routing and provisioning)."""

    provider_type: str

    def verify_webhook(self, request) -> bool: ...

    def parse_events(self, payload: dict[str, Any]) -> list[ProviderEvent]: ...


@runtime_checkable
class NotificationProvider(Protocol):
    """Anything that can deliver a notification to a patient."""

    provider_type: str

    def send(
        self,
        *,
        clinic,
        patient,
        template_id: str,
        body: str = "",
        appointment=None,
        payload: dict[str, Any] | None = None,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Signature helpers
# ---------------------------------------------------------------------------
def verify_hmac_sha256(body: bytes, header_value: str, secret: str) -> bool:
    """Verify an ``sha256=<hex>`` HMAC signature header."""
    if not header_value or not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    provided = header_value.split("=", 1)[-1].strip().lower()
    return hmac.compare_digest(expected, provided)


def verify_hmac_sha1(url: str, params: dict[str, Any], header_value: str, secret: str) -> bool:
    """Verify a Twilio-style ``X-Twilio-Signature`` (HMAC-SHA1)."""
    if not header_value or not secret:
        return False
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, header_value.strip().lower())


def verify_secret_token(candidate: str | None, expected: str | None) -> bool:
    if not candidate or not expected:
        return False
    return hmac.compare_digest(candidate, expected)


def webhook_path_secret(request) -> str:
    """Read the shared secret carried in the webhook URL path.

    Providers that cannot sign the body (Sarvam, for instance) put the
    shared secret in the URL. The webhook endpoints are plain Django views,
    so the keyword arguments live on ``request.resolver_match``; DRF
    requests carry them on ``parser_context`` instead. Both are checked.
    """
    resolver_match = getattr(request, "resolver_match", None)
    kwargs = getattr(resolver_match, "kwargs", None) or {}
    if kwargs.get("secret"):
        return str(kwargs["secret"])

    parser_context = getattr(request, "parser_context", None) or {}
    kwargs = parser_context.get("kwargs", {}) or {}
    return str(kwargs.get("secret", "") or "")
