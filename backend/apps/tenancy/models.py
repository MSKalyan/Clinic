"""Tenant, configuration and provider-connection models."""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models

from apps.core.constants import (
    AccountMode,
    Channel,
    ClinicStatus,
    ConnectionStatus,
    ProviderType,
)
from apps.core.models import ClinicOwnedModel, TimeStampedModel, UUIDModel

#: Default weekly operating hours used when a clinic has not customised them.
DEFAULT_OPERATING_HOURS: dict[str, Any] = {
    # Monday..Sunday
    "mon": {"open": "09:00", "close": "19:00", "closed": False},
    "tue": {"open": "09:00", "close": "19:00", "closed": False},
    "wed": {"open": "09:00", "close": "19:00", "closed": False},
    "thu": {"open": "09:00", "close": "19:00", "closed": False},
    "fri": {"open": "09:00", "close": "19:00", "closed": False},
    "sat": {"open": "09:00", "close": "14:00", "closed": False},
    "sun": {"open": "09:00", "close": "14:00", "closed": True},
}

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def default_operating_hours() -> dict[str, Any]:
    """A fresh copy of the default operating hours.

    A named function (rather than a lambda) so that Django's migration
    writer can serialise the default.
    """
    return {key: dict(value) for key, value in DEFAULT_OPERATING_HOURS.items()}


class Clinic(UUIDModel, TimeStampedModel):
    """A tenant. Every other domain row hangs off one of these."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    status = models.CharField(
        max_length=20, choices=[(s.value, s.value) for s in ClinicStatus], default=ClinicStatus.ONBOARDING
    )
    onboarded_at = models.DateTimeField(null=True, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "clinics"
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.name} ({self.slug})"

    @property
    def is_active(self) -> bool:
        return self.status == ClinicStatus.ACTIVE

    @property
    def settings(self) -> "ClinicSettings":
        obj, _ = ClinicSettings.objects.get_or_create(clinic=self)
        return obj

    def appointment_rules(self) -> dict[str, Any]:
        return self.settings.resolved_appointment_rules()

    def reminder_policy(self) -> dict[str, Any]:
        return self.settings.resolved_reminder_policy()

    def escalation_policy(self) -> dict[str, Any]:
        return self.settings.resolved_escalation_policy()

    def status_freshness_minutes(self) -> dict[str, int]:
        return self.settings.resolved_status_freshness_minutes()

    def operating_hours(self) -> dict[str, Any]:
        return self.settings.operating_hours

    def is_open_at(self, moment) -> bool:  # noqa: ANN001
        """Is the clinic open at ``moment`` (an aware datetime, UTC)?"""
        from apps.core.timeutils import clinic_zone, to_clinic_local

        local = to_clinic_local(moment, self)
        window = self.operating_hours().get(_WEEKDAY_KEYS[local.weekday()], {})
        if not window or window.get("closed"):
            return False
        from datetime import datetime

        open_at = datetime.strptime(window["open"], "%H:%M").time()
        close_at = datetime.strptime(window["close"], "%H:%M").time()
        return open_at <= local.time() <= close_at


class ClinicSettings(TimeStampedModel):
    """Per-clinic configuration. One row per clinic."""

    clinic = models.OneToOneField(
        Clinic, on_delete=models.CASCADE, related_name="config", primary_key=True
    )
    operating_hours = models.JSONField(default=default_operating_hours)
    default_language = models.CharField(max_length=16, default="hi-IN")
    supported_languages = models.JSONField(default=list)
    appointment_rules = models.JSONField(default=dict)
    reminder_policy = models.JSONField(default=dict)
    escalation_policy = models.JSONField(default=dict)
    status_freshness_minutes = models.JSONField(default=dict)
    privacy_notice_url = models.URLField(blank=True, default="")
    updated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinic_settings_updates",
    )

    class Meta:
        db_table = "clinic_settings"

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"ClinicSettings({self.clinic_id})"

    # NOTE: these are deliberately *not* named like the fields they read.
    # A method that shares a name with a model field silently replaces the
    # field in the class body, and the column never reaches the database.

    def resolved_appointment_rules(self) -> dict[str, Any]:
        return {**settings.DEFAULT_APPOINTMENT_RULES, **(self.appointment_rules or {})}

    def resolved_reminder_policy(self) -> dict[str, Any]:
        return {**settings.DEFAULT_REMINDER_POLICY, **(self.reminder_policy or {})}

    def resolved_escalation_policy(self) -> dict[str, Any]:
        return {**settings.DEFAULT_ESCALATION_POLICY, **(self.escalation_policy or {})}

    def resolved_status_freshness_minutes(self) -> dict[str, int]:
        defaults = dict(settings.DEFAULT_STATUS_FRESHNESS_MINUTES)
        defaults.update(self.status_freshness_minutes or {})
        return defaults


class ClinicAgentConfig(UUIDModel, TimeStampedModel):
    """The assistant's persona/instructions for a clinic."""

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name="agent_configs")
    name = models.CharField(max_length=120, default="Default")
    greeting = models.TextField(
        default=(
            "You are the virtual receptionist for this clinic. "
            "Introduce yourself as an automated assistant and offer help."
        )
    )
    agent_instructions = models.TextField(blank=True, default="")
    enabled_channels = models.JSONField(default=list)
    voice_language = models.CharField(max_length=16, default="hi-IN")
    configuration_version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, default="active")
    is_default = models.BooleanField(default=True)

    class Meta:
        db_table = "clinic_agent_configs"
        ordering = ["-configuration_version"]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"ClinicAgentConfig({self.clinic_id} v{self.configuration_version})"


class ProviderConnection(ClinicOwnedModel):
    """A link between a clinic and an external provider account.

    Credentials are never stored here -- only a ``secret_reference`` pointer
    into the secrets manager (PRD 9.2).
    """

    provider_type = models.CharField(
        max_length=20, choices=[(p.value, p.value) for p in ProviderType]
    )
    account_mode = models.CharField(
        max_length=20,
        choices=[(m.value, m.value) for m in AccountMode],
        default=AccountMode.SHARED,
    )
    external_account_id = models.CharField(max_length=200, blank=True, default="")
    secret_reference = models.CharField(max_length=400, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in ConnectionStatus],
        default=ConnectionStatus.PENDING,
    )
    display_name = models.CharField(max_length=120, blank=True, default="")
    config = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "provider_connections"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "provider_type", "account_mode", "external_account_id"],
                name="uniq_provider_connection_per_clinic",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.provider_type}:{self.account_mode}:{self.clinic_id}"


class ClinicChannelNumber(ClinicOwnedModel):
    """A phone number (voice or WhatsApp) that routes to a clinic."""

    channel = models.CharField(max_length=20, choices=[(c.value, c.value) for c in Channel])
    provider_connection = models.ForeignKey(
        ProviderConnection,
        on_delete=models.PROTECT,
        related_name="channel_numbers",
        null=True,
        blank=True,
    )
    external_number_id = models.CharField(max_length=200)
    display_number = models.CharField(max_length=40, blank=True, default="")
    routing_status = models.CharField(max_length=20, default="active")
    capabilities = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "clinic_channel_numbers"
        constraints = [
            models.UniqueConstraint(
                fields=["provider_connection", "external_number_id"],
                name="uniq_channel_number_per_provider",
            ),
            models.UniqueConstraint(
                fields=["channel", "display_number"],
                name="uniq_channel_display_number",
                condition=~models.Q(display_number=""),
            ),
        ]
        indexes = [models.Index(fields=["channel", "external_number_id"], name="channel_lookup_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.channel}:{self.display_number or self.external_number_id}"


class ClinicSecret(ClinicOwnedModel):
    """A provider credential a clinic has set for itself.

    The value is stored **encrypted** (see ``apps.core.secrets``) and is
    never returned by the API. The ``fingerprint`` is a short,
    non-reversible digest that lets the interface confirm which key is
    stored without revealing any part of it.

    One row per key per clinic. The platform-wide environment variable is
    the fallback for clinics that have not set their own -- it is not
    copied here.
    """

    #: The logical key, e.g. ``sarvam.api_key``. See ``apps.core.secrets``.
    key = models.CharField(max_length=100)
    #: The encrypted value. Fernet ciphertext, never plaintext.
    ciphertext = models.TextField()
    #: A short, non-reversible digest, e.g. ``...4f2a (3a91c0be)``.
    fingerprint = models.CharField(max_length=40, blank=True, default="")
    updated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_clinic_secrets",
    )

    class Meta:
        db_table = "clinic_secrets"
        constraints = [
            models.UniqueConstraint(fields=["clinic", "key"], name="uniq_clinic_secret_key")
        ]
        indexes = [models.Index(fields=["clinic", "key"], name="clinic_secret_lookup_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.clinic_id}:{self.key}"
