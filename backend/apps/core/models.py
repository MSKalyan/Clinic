"""Abstract base models and shared infrastructure tables."""
from __future__ import annotations

import uuid
from typing import Any

from django.db import models
from django.utils import timezone

from apps.core.constants import AuditAction


class UUIDModel(models.Model):
    """Primary keys are UUIDs so IDs are not enumerable across tenants."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ClinicOwnedQuerySet(models.QuerySet):
    """QuerySet that can be hard-scoped to a single clinic."""

    def for_clinic(self, clinic: Any) -> "ClinicOwnedQuerySet":
        return self.filter(clinic_id=getattr(clinic, "id", clinic))


class ClinicOwnedManager(models.Manager.from_queryset(ClinicOwnedQuerySet)):
    def for_clinic(self, clinic: Any) -> ClinicOwnedQuerySet:
        return self.get_queryset().for_clinic(clinic)


class ClinicOwnedModel(UUIDModel, TimeStampedModel):
    """Base class for every row that belongs to exactly one clinic.

    The ``clinic`` FK gives us the ``clinic_id`` column used by the
    PostgreSQL Row Level Security policies (see the ``enable_rls`` migration).

    The primary key is a UUID rather than a sequence, so identifiers cannot
    be enumerated across tenants: ``/patients/1``, ``/patients/2`` ... would
    otherwise walk the whole table, and would tell an attacker how many
    records a *different* clinic holds.
    """

    clinic = models.ForeignKey(
        "tenancy.Clinic",
        on_delete=models.CASCADE,
        related_name="%(class)s_set",
    )

    objects = ClinicOwnedManager()

    class Meta:
        abstract = True


class AuditLog(models.Model):
    """Append-only record of important actions.

    Rows are never updated or deleted through the ORM: ``save()`` on an
    existing row and ``delete()`` both raise. This satisfies PRD 9.6
    ("audit logs must be protected against unauthorised modification").
    """

    id = models.BigAutoField(primary_key=True)
    clinic = models.ForeignKey(
        "tenancy.Clinic",
        on_delete=models.CASCADE,
        related_name="audit_logs",
        null=True,
        blank=True,
    )
    actor_id = models.UUIDField(null=True, blank=True)
    actor_role = models.CharField(max_length=50, blank=True, default="")
    action = models.CharField(max_length=50, choices=[(a.value, a.value) for a in AuditAction])
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, blank=True, default="")
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    request_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["clinic", "-timestamp"], name="audit_clinic_ts_idx"),
            models.Index(fields=["resource_type", "resource_id"], name="audit_resource_idx"),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk and not self._state.adding:
            raise PermissionError("Audit log entries are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        raise PermissionError("Audit log entries cannot be deleted.")

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"AuditLog({self.action} {self.resource_type}:{self.resource_id})"


class OutboxEvent(models.Model):
    """Transactional outbox.

    Domain services write the event inside the same transaction as the
    business change; a Celery task then publishes it to the outside world.
    This guarantees "database changes must trigger external work" without a
    dual-write race (PRD 11.2).
    """

    id = models.BigAutoField(primary_key=True)
    clinic = models.ForeignKey(
        "tenancy.Clinic",
        on_delete=models.CASCADE,
        related_name="outbox_events",
        null=True,
        blank=True,
    )
    event_type = models.CharField(max_length=80, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="pending", db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "outbox_events"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["status", "created_at"], name="outbox_status_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"OutboxEvent({self.event_type} {self.pk})"


class IdempotencyRecord(models.Model):
    """Generic idempotency guard for externally-triggered operations."""

    id = models.BigAutoField(primary_key=True)
    clinic = models.ForeignKey(
        "tenancy.Clinic",
        on_delete=models.CASCADE,
        related_name="idempotency_records",
        null=True,
        blank=True,
    )
    key = models.CharField(max_length=200)
    scope = models.CharField(max_length=80)
    response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "idempotency_records"
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "scope", "key"], name="uniq_idempotency_scope_key"
            )
        ]
