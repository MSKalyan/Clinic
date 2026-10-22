"""Persistence for provider events.

Every accepted provider event is stored with its provider event id so that
a duplicate delivery is recognised and ignored (PRD 10.6).
"""
from __future__ import annotations

from django.db import models

from apps.core.models import UUIDModel


class ProviderEvent(UUIDModel, models.Model):
    """A raw, normalised provider event awaiting processing."""

    provider_type = models.CharField(max_length=40, db_index=True)
    provider_event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=60, db_index=True)
    clinic = models.ForeignKey(
        "tenancy.Clinic",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="provider_events",
    )
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, default="received", db_index=True)
    error = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "provider_events"
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider_type", "provider_event_id"],
                name="uniq_provider_event_per_provider",
            )
        ]
        indexes = [
            models.Index(fields=["clinic", "status"], name="provider_event_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.provider_type}:{self.event_type}:{self.provider_event_id}"
