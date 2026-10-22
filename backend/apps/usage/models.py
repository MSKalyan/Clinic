"""Usage metering and subscription records."""
from __future__ import annotations

from django.db import models

from apps.core.models import ClinicOwnedModel, TimeStampedModel, UUIDModel


class UsageEvent(ClinicOwnedModel):
    """One metered unit of consumption.

    Every row carries the tenant, a provider reference, a quantity, a unit
    and an idempotency key so that provider invoices can be reconciled
    against what we recorded (PRD 15.3).
    """

    provider_connection = models.ForeignKey(
        "tenancy.ProviderConnection",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_events",
    )
    event_type = models.CharField(max_length=60, db_index=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=30)
    #: What the provider charged us.
    provider_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    #: What we may bill the customer (may differ from provider cost).
    billable_quantity = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    provider_reference = models.CharField(max_length=200, blank=True, default="")
    recorded_at = models.DateTimeField(db_index=True)
    idempotency_key = models.CharField(max_length=200, unique=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "usage_events"
        ordering = ["-recorded_at"]
        indexes = [
            models.Index(fields=["clinic", "event_type", "recorded_at"], name="usage_lookup_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.event_type} {self.quantity}{self.unit} for {self.clinic_id}"


class ClinicSubscription(UUIDModel, TimeStampedModel):
    """The clinic's plan and billing period."""

    clinic = models.OneToOneField(
        "tenancy.Clinic", on_delete=models.CASCADE, related_name="subscription"
    )
    plan_id = models.CharField(max_length=60, default="starter")
    billing_status = models.CharField(max_length=30, default="active")
    billing_period_start = models.DateField(null=True, blank=True)
    billing_period_end = models.DateField(null=True, blank=True)
    provider_customer_reference = models.CharField(max_length=200, blank=True, default="")
    included_voice_minutes = models.PositiveIntegerField(default=0)
    included_messages = models.PositiveIntegerField(default=0)
    overage_price_voice_minute = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    overage_price_message = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    class Meta:
        db_table = "clinic_subscriptions"

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.clinic_id} on {self.plan_id}"
