"""Provider registry.

Resolves the adapter for a clinic from its ``ProviderConnection`` rows.
Credentials are read from the secrets manager via ``secret_reference``; the
plaintext never touches the database (PRD 9.2).
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from apps.core.constants import Channel, ConnectionStatus, ProviderType
from apps.integrations.providers.sarvam import SarvamVoiceAdapter
from apps.integrations.providers.telephony import TelephonyAdapter
from apps.integrations.providers.waha import WahaAdapter
from apps.integrations.providers.whatsapp import WhatsAppCloudAdapter

logger = logging.getLogger("apps.integrations.registry")


def resolve_secret(reference: str) -> dict[str, Any]:
    """Fetch a secret bundle from the secrets manager.

    In local development the reference is treated as an env var name so that
    secrets never have to be committed. In production this is where an AWS
    Secrets Manager call belongs.
    """
    if not reference:
        return {}
    import os

    raw = os.environ.get(reference)
    if raw:
        try:
            import json

            return json.loads(raw)
        except json.JSONDecodeError:
            return {"token": raw}
    logger.warning("secret reference %s could not be resolved", reference)
    return {}


def _connection(clinic, provider_type: str):
    from apps.tenancy.models import ProviderConnection

    return (
        ProviderConnection.objects.filter(
            clinic=clinic,
            provider_type=provider_type,
            status=ConnectionStatus.ACTIVE,
        )
        .order_by("-created_at")
        .first()
    )


def _clinic_key(clinic, key: str, default: str = "") -> str:
    """Resolve a configuration key for a clinic.

    The clinic's own value wins; the platform setting is the fallback;
    a secret-manager reference, when one is configured for the clinic, is
    consulted in between.

    The order matters: a clinic that has brought its own provider
    account must not be silently overridden by the platform's shared
    account.
    """
    from apps.core.secrets import resolve as resolve_key

    value, _source = resolve_key(clinic, key)
    if value:
        return value
    return default


def get_voice_provider(clinic, provider: str = "sarvam"):
    """Return the voice adapter for a clinic."""
    connection = _connection(clinic, ProviderType.VOICE)
    secret = resolve_secret(connection.secret_reference if connection else "")
    if provider == "sarvam":
        return SarvamVoiceAdapter(
            webhook_secret=secret.get("webhook_secret")
            or _clinic_key(clinic, "sarvam.webhook_secret", settings.SARVAM_WEBHOOK_SECRET),
            api_key=secret.get("api_key")
            or _clinic_key(clinic, "sarvam.api_key", settings.SARVAM_API_KEY),
        )
    return None


def get_messaging_provider(clinic, channel: str = Channel.WHATSAPP):
    """Return the messaging adapter for a clinic and channel.

    A clinic with its own Meta WhatsApp Cloud account keeps using it. When no
    Cloud credentials are configured, the self-hosted WAHA session is the
    WhatsApp provider for this deployment, so transactional messages (and
    reminders) go through the same number that receives patient replies.
    """
    if channel == Channel.WHATSAPP:
        connection = _connection(clinic, ProviderType.MESSAGING)
        secret = resolve_secret(connection.secret_reference if connection else "")
        access_token = secret.get("access_token") or _clinic_key(
            clinic, "whatsapp.access_token", settings.WHATSAPP_ACCESS_TOKEN
        )
        phone_number_id = secret.get("phone_number_id") or _clinic_key(
            clinic, "whatsapp.phone_number_id", settings.WHATSAPP_PHONE_NUMBER_ID
        )
        if not (access_token and phone_number_id) and settings.WAHA_API_KEY:
            return get_waha_adapter()
        return WhatsAppCloudAdapter(
            app_secret=secret.get("app_secret")
            or _clinic_key(clinic, "whatsapp.app_secret", settings.WHATSAPP_APP_SECRET),
            access_token=access_token,
            phone_number_id=phone_number_id,
        )
    return None


def get_telephony_provider(clinic):
    connection = _connection(clinic, ProviderType.TELEPHONY)
    secret = resolve_secret(connection.secret_reference if connection else "")
    return TelephonyAdapter(
        auth_token=secret.get("auth_token")
        or _clinic_key(clinic, "telephony.auth_token", settings.TELEPHONY_AUTH_TOKEN)
    )


def get_waha_adapter() -> WahaAdapter:
    """Return the WAHA webhook adapter from platform settings."""
    return WahaAdapter(
        webhook_secret=settings.WAHA_WEBHOOK_SECRET,
        hmac_key=settings.WAHA_WEBHOOK_HMAC_KEY,
        session=settings.WAHA_SESSION,
    )


def get_provider_for_webhook(provider: str, secret: str = ""):
    """Adapters usable without a resolved clinic (webhook endpoints).

    ``secret`` is the secret **we** hold for the provider -- the value that
    arrived with the request is only ever a candidate and is never passed
    in here. Handing the request's own secret to the adapter would make
    every signature check pass, because the candidate would be compared
    with itself.
    """
    if provider == "sarvam":
        return SarvamVoiceAdapter(
            webhook_secret=secret or settings.SARVAM_WEBHOOK_SECRET,
            api_key=settings.SARVAM_API_KEY,
        )
    if provider == "whatsapp":
        return WhatsAppCloudAdapter(
            app_secret=secret or settings.WHATSAPP_APP_SECRET,
            access_token=settings.WHATSAPP_ACCESS_TOKEN,
            phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID,
        )
    if provider == "telephony":
        return TelephonyAdapter(auth_token=secret or settings.TELEPHONY_AUTH_TOKEN)
    if provider == "waha":
        return get_waha_adapter()
    return None
