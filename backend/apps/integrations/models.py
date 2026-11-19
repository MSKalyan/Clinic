"""Persistence for provider events.

Every accepted provider event is stored with its provider event id so that
a duplicate delivery is recognised and ignored (PRD 10.6).
"""
from __future__ import annotations

from django.db import models

from apps.core.models import UUIDModel


class WhatsAppFlow(UUIDModel, models.Model):
    """State of the WhatsApp booking assistant for one patient chat.

    A single WAHA session may serve several clinics; the clinic is resolved
    from the sender's existing patient record, a configured default slug, or
    the sole active clinic. Only one flow exists per (clinic, chat).
    """

    class State(models.TextChoices):
        MENU = "MENU", "Main menu"
        NAME = "NAME", "Awaiting patient name"
        PHONE = "PHONE", "Awaiting phone number"
        DOCTOR = "DOCTOR", "Awaiting doctor"
        DATE = "DATE", "Awaiting date"
        SLOT = "SLOT", "Awaiting slot"
        CONFIRM = "CONFIRM", "Awaiting confirmation"
        DONE = "DONE", "Booking completed"
        HANDOFF = "HANDOFF", "Human handoff requested"

    clinic = models.ForeignKey(
        "tenancy.Clinic", on_delete=models.CASCADE, related_name="whatsapp_flows"
    )
    chat_id = models.CharField(max_length=200)
    sender_phone = models.CharField(max_length=40, blank=True, default="")
    state = models.CharField(
        max_length=20, choices=State.choices, default=State.MENU, db_index=True
    )
    #: Answers collected so far: service, name, phone, doctor_id, date, slot.
    context = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "waha_flows"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["clinic", "chat_id"], name="uniq_whatsapp_flow_per_chat"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"WhatsApp flow {self.chat_id} ({self.state})"


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


class WahaMessageLog(models.Model):
    """Minimal, persistent log of WhatsApp text messages handled via WAHA.

    Deliberately independent of a clinic FK: the local WAHA session is a
    single WhatsApp number and is not mapped to a tenant by this initial
    integration. The unique ``message_id`` is the idempotency guard -- a
    redelivered webhook is acknowledged but never processed twice.
    """

    class Direction(models.TextChoices):
        INBOUND = "INBOUND", "Inbound"
        OUTBOUND = "OUTBOUND", "Outbound"

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        PENDING = "PENDING", "Reply queued"
        REPLIED = "REPLIED", "Replied"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"

    id = models.BigAutoField(primary_key=True)
    message_id = models.CharField(max_length=255, unique=True)
    session = models.CharField(max_length=100, blank=True, default="")
    sender_id = models.CharField(max_length=255, blank=True, default="")
    sender_phone = models.CharField(max_length=40, blank=True, default="")
    text = models.TextField(blank=True, default="")
    direction = models.CharField(
        max_length=10, choices=Direction.choices, default=Direction.INBOUND, db_index=True
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.RECEIVED, db_index=True
    )
    #: Provider id of the automated reply, when WAHA accepted the send.
    reply_message_id = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")
    timestamp = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "waha_message_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session", "created_at"], name="waha_log_session_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.direction} {self.message_id} ({self.status})"
