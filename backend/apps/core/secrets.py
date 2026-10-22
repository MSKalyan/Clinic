"""Per-clinic provider credentials.

Every clinic brings its own provider accounts: its own WhatsApp business
number, its own voice agent, its own telephony account. Those credentials
have to be stored somewhere the platform controls, so they live in the
database -- **encrypted**, and never returned by the API.

Three rules this module enforces:

1. **The value is never returned.** The API reports *whether* a key is
   set and nothing more. There is no code path that reads a secret out
   and hands it to a client.
2. **The value is never logged.** ``fingerprint`` is a short,
   non-reversible digest, so the UI can show "ends in 4f2a" and confirm a
   clinic pasted the key they meant to, without revealing anything.
3. **The platform setting is a fallback, not the source.** A clinic that
   sets its own key always wins; the environment variable is only the
   shared default for clinics that have not set their own.

The encryption key comes from ``SECRET_ENCRYPTION_KEY``. If it is not
set, one is derived from ``INTERNAL_SERVICE_TOKEN_PEPPER`` so that a
local development setup works out of the box -- with a warning, because
rotating the pepper would then invalidate every stored secret.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings

logger = logging.getLogger("apps.core.secrets")

#: The scopes a key can have.
SCOPE_CLINIC = "clinic"
SCOPE_PLATFORM = "platform"


@dataclass(frozen=True)
class KeySpec:
    """One configuration key the platform cares about."""

    #: Stable identifier, e.g. ``sarvam.api_key``. This is what the API
    #: and the database use.
    key: str
    #: What a human calls it.
    label: str
    #: What it is for, in one sentence.
    purpose: str
    #: ``clinic`` -- the clinic sets it. ``platform`` -- the operator sets it.
    scope: str
    #: The group it appears under in the UI.
    group: str
    #: The environment variable that holds the platform-wide default.
    env_var: str
    #: Whether the feature works without it.
    required: bool = True
    #: Whether the value is sensitive (never echoed, always masked).
    secret: bool = True
    #: Where the value goes when the provider is called.
    provider_field: str = ""


#: Every key the platform knows about, grouped for the UI.
KEY_SPECS: tuple[KeySpec, ...] = (
    # -- Voice ------------------------------------------------------------
    KeySpec(
        key="sarvam.api_key",
        label="Sarvam API key",
        purpose="Authenticates calls to the Sarvam voice API.",
        scope=SCOPE_CLINIC,
        group="voice",
        env_var="SARVAM_API_KEY",
        provider_field="api_key",
    ),
    KeySpec(
        key="sarvam.voice_agent_id",
        label="Voice agent ID",
        purpose="Which of your Sarvam voice agents answers the clinic's calls.",
        scope=SCOPE_CLINIC,
        group="voice",
        env_var="SARVAM_VOICE_AGENT_ID",
        secret=False,
    ),
    KeySpec(
        key="sarvam.webhook_secret",
        label="Voice webhook secret",
        purpose="Verifies that a voice callback really came from Sarvam.",
        scope=SCOPE_CLINIC,
        group="voice",
        env_var="SARVAM_WEBHOOK_SECRET",
    ),
    # -- Messaging --------------------------------------------------------
    KeySpec(
        key="whatsapp.phone_number_id",
        label="WhatsApp phone number ID",
        purpose="The Meta phone-number ID patients message this clinic on.",
        scope=SCOPE_CLINIC,
        group="messaging",
        env_var="WHATSAPP_PHONE_NUMBER_ID",
        secret=False,
    ),
    KeySpec(
        key="whatsapp.access_token",
        label="WhatsApp access token",
        purpose="Lets the platform send WhatsApp messages as the clinic.",
        scope=SCOPE_CLINIC,
        group="messaging",
        env_var="WHATSAPP_ACCESS_TOKEN",
    ),
    KeySpec(
        key="whatsapp.app_secret",
        label="WhatsApp app secret",
        purpose="Verifies the signature on WhatsApp webhooks.",
        scope=SCOPE_CLINIC,
        group="messaging",
        env_var="WHATSAPP_APP_SECRET",
    ),
    KeySpec(
        key="whatsapp.verify_token",
        label="WhatsApp verify token",
        purpose="The token Meta asks for when you register the webhook.",
        scope=SCOPE_CLINIC,
        group="messaging",
        env_var="WHATSAPP_VERIFY_TOKEN",
        secret=False,
    ),
    # -- Telephony --------------------------------------------------------
    KeySpec(
        key="telephony.base_url",
        label="Telephony API URL",
        purpose="Where the platform sends call-routing instructions.",
        scope=SCOPE_CLINIC,
        group="telephony",
        env_var="TELEPHONY_BASE_URL",
        secret=False,
    ),
    KeySpec(
        key="telephony.auth_token",
        label="Telephony auth token",
        purpose="Authenticates the platform against the telephony provider.",
        scope=SCOPE_CLINIC,
        group="telephony",
        env_var="TELEPHONY_AUTH_TOKEN",
    ),
    KeySpec(
        key="telephony.provider",
        label="Telephony provider",
        purpose="Which telephony provider this clinic is on.",
        scope=SCOPE_CLINIC,
        group="telephony",
        env_var="TELEPHONY_PROVIDER",
        secret=False,
    ),
    # -- Platform ---------------------------------------------------------
    KeySpec(
        key="platform.django_secret_key",
        label="Application secret key",
        purpose="Signs the staff sessions. Set by whoever runs the platform.",
        scope=SCOPE_PLATFORM,
        group="platform",
        env_var="DJANGO_SECRET_KEY",
    ),
    KeySpec(
        key="platform.service_token_pepper",
        label="Service token pepper",
        purpose="Hashes the tokens providers use to call the API.",
        scope=SCOPE_PLATFORM,
        group="platform",
        env_var="INTERNAL_SERVICE_TOKEN_PEPPER",
    ),
)

#: Look-up by key.
KEY_SPECS_BY_KEY: dict[str, str] = {spec.key: spec for spec in KEY_SPECS}

#: Human labels for the groups.
GROUP_LABELS: dict[str, str] = {
    "voice": "Voice",
    "messaging": "WhatsApp",
    "telephony": "Telephony",
    "platform": "Platform",
}

#: The order the groups appear in.
GROUP_ORDER: tuple[str, ...] = ("voice", "messaging", "telephony", "platform")


def get_spec(key: str) -> KeySpec | None:
    return KEY_SPECS_BY_KEY.get(key)


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------
def _encryption_key() -> bytes:
    """The Fernet key used to encrypt stored secrets.

    A 32-byte URL-safe base64 key. If ``SECRET_ENCRYPTION_KEY`` is not
    set, one is derived from the service-token pepper so local
    development works without extra setup.
    """
    from cryptography.fernet import Fernet

    configured = (getattr(settings, "SECRET_ENCRYPTION_KEY", "") or "").strip()
    if configured:
        # Accept either a ready-made Fernet key or any passphrase.
        try:
            Fernet(configured.encode())
            return configured.encode()
        except (ValueError, TypeError):
            digest = hashlib.sha256(configured.encode()).digest()
            return base64.urlsafe_b64encode(digest)

    pepper = getattr(settings, "INTERNAL_SERVICE_TOKEN_PEPPER", "") or ""
    if not pepper:
        raise RuntimeError(
            "SECRET_ENCRYPTION_KEY is not set and INTERNAL_SERVICE_TOKEN_PEPPER is empty, "
            "so clinic secrets cannot be encrypted. Set SECRET_ENCRYPTION_KEY."
        )
    logger.warning(
        "SECRET_ENCRYPTION_KEY is not set; deriving the encryption key from "
        "INTERNAL_SERVICE_TOKEN_PEPPER. Rotating the pepper will invalidate "
        "every stored clinic secret."
    )
    digest = hashlib.sha256(f"clinic-secrets:{pepper}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(value: str) -> str:
    """Encrypt a secret for storage."""
    from cryptography.fernet import Fernet

    return Fernet(_encryption_key()).encrypt(value.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored secret."""
    from cryptography.fernet import Fernet

    return Fernet(_encryption_key()).decrypt(ciphertext.encode()).decode()


def fingerprint(value: str) -> str:
    """A short, non-reversible digest of a secret.

    Lets the UI confirm that a clinic pasted the key they meant to
    ("...4f2a (3a91c0be)") without ever revealing any part of it.
    """
    digest = hashlib.sha256(value.encode()).hexdigest()[:8]
    tail = value[-4:] if len(value) >= 4 else "****"
    return f"...{tail} ({digest})"


# ---------------------------------------------------------------------------
# Reading and writing
# ---------------------------------------------------------------------------
def platform_value(spec: KeySpec) -> str:
    """The platform-wide default for a key, from the environment."""
    return str(getattr(settings, spec.env_var, "") or "").strip()


def get_clinic_value(clinic, key: str) -> str:
    """The value a clinic has set for a key, or ``""``.

    The clinic's own value wins over the platform default. The stored
    ciphertext is decrypted here and nowhere else.

    The database session is scoped to the clinic for the read. The
    ``clinic_secrets`` table has a row-level security policy, so a read
    without a scope finds nothing -- which would make this function
    silently return "" outside a request that happens to be scoped.
    """
    from apps.core.rls import rls_scope
    from apps.tenancy.models import ClinicSecret

    with rls_scope(str(clinic.id)):
        row = (
            ClinicSecret.objects.filter(clinic=clinic, key=key)
            .only("ciphertext")
            .first()
        )
    if row is None:
        return ""
    try:
        return decrypt(row.ciphertext)
    except Exception:  # pragma: no cover - a rotated key or a corrupt row
        logger.exception("could not decrypt the clinic secret for %s", key)
        return ""


def resolve(clinic, key: str) -> tuple[str, str]:
    """Resolve a key for a clinic.

    Returns ``(value, source)`` where source is ``"clinic"`` when the
    clinic set it and ``"platform"`` when the shared default applies.
    """
    own = get_clinic_value(clinic, key)
    if own:
        return own, "clinic"
    spec = get_spec(key)
    if spec is None:
        return "", "missing"
    default = platform_value(spec)
    if default:
        return default, "platform"
    return "", "missing"


def set_clinic_value(clinic, key: str, value: str, actor=None) -> None:
    """Store (or replace) a clinic's own value for a key."""
    from apps.core.rls import rls_scope
    from apps.tenancy.models import ClinicSecret

    if key not in KEY_SPECS_BY_KEY:
        raise KeyError(key)

    with rls_scope(str(clinic.id)):
        ClinicSecret.objects.update_or_create(
            clinic=clinic,
            key=key,
            defaults={
                "ciphertext": encrypt(value),
                "fingerprint": fingerprint(value),
                "updated_by": actor if getattr(actor, "pk", None) else None,
            },
        )


def clear_clinic_value(clinic, key: str) -> bool:
    """Remove a clinic's own value. Returns whether anything was removed."""
    from apps.core.rls import rls_scope
    from apps.tenancy.models import ClinicSecret

    with rls_scope(str(clinic.id)):
        deleted, _ = ClinicSecret.objects.filter(clinic=clinic, key=key).delete()
    return bool(deleted)


def describe(clinic) -> list[dict[str, Any]]:
    """The configuration status of every key, for the clinic.

    This is the whole payload the UI renders. It contains no secret
    values -- only whether each key is set, and where the value came from.
    """
    from apps.tenancy.models import ClinicSecret

    from apps.core.rls import rls_scope

    with rls_scope(str(clinic.id)):
        stored = {
            row.key: row
            for row in ClinicSecret.objects.filter(clinic=clinic).only(
                "key", "fingerprint", "updated_at"
            )
        }

    described: list[dict[str, Any]] = []
    for spec in KEY_SPECS:
        own = stored.get(spec.key)
        platform = platform_value(spec)

        if own is not None:
            status = "set"
        elif platform:
            status = "platform"
        else:
            status = "missing"

        described.append(
            {
                "key": spec.key,
                "label": spec.label,
                "purpose": spec.purpose,
                "group": spec.group,
                "group_label": GROUP_LABELS.get(spec.group, spec.group.title()),
                "scope": spec.scope,
                "required": spec.required,
                "secret": spec.secret,
                "env_var": spec.env_var,
                "status": status,
                "is_set": status in {"set", "platform"},
                "source": "clinic" if status == "set" else ("platform" if status == "platform" else ""),
                "fingerprint": own.fingerprint if own else "",
                "updated_at": own.updated_at.isoformat() if own else None,
                "editable": spec.scope == SCOPE_CLINIC,
            }
        )
    return described
