"""Conversations, messages, call logs, follow-up tasks and notification logs."""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core.constants import (
    CallOutcome,
    Channel,
    ConversationStatus,
    DeliveryStatus,
    FollowUpTaskType,
    TaskPriority,
    TaskStatus,
)
from apps.core.models import ClinicOwnedModel


class Conversation(ClinicOwnedModel):
    """A patient interaction, on any channel."""

    patient = models.ForeignKey(
        "appointments.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    channel = models.CharField(max_length=20, choices=[(c.value, c.value) for c in Channel])
    provider_conversation_id = models.CharField(max_length=200, blank=True, default="", db_index=True)
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in ConversationStatus],
        default=ConversationStatus.OPEN,
    )
    language = models.CharField(max_length=16, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    outcome = models.CharField(
        max_length=30, choices=[(o.value, o.value) for o in CallOutcome], blank=True, default=""
    )
    escalation_reason = models.CharField(max_length=255, blank=True, default="")
    taken_over_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="taken_over_conversations",
    )
    started_at = models.DateTimeField(default=timezone.now, null=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversations"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "-created_at"], name="conversation_clinic_idx"),
            models.Index(fields=["clinic", "status"], name="conversation_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.channel} conversation {self.id}"


class ConversationMessage(ClinicOwnedModel):
    """A single turn in a conversation.

    ``content_reference`` points at the retained content (if any). Full
    transcripts are not retained indefinitely -- see ``RETENTION`` settings.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    direction = models.CharField(max_length=10)  # inbound | outbound
    message_type = models.CharField(max_length=30, default="text")
    provider_message_id = models.CharField(max_length=200, blank=True, default="")
    content_reference = models.CharField(max_length=500, blank=True, default="")
    #: Short, non-identifying snippet used for the operational summary.
    excerpt = models.CharField(max_length=280, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "conversation_messages"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"], name="message_conv_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.direction} message {self.id}"


class CallLog(ClinicOwnedModel):
    """The operational record of a phone call."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="call_logs",
    )
    provider_call_id = models.CharField(max_length=200, db_index=True)
    direction = models.CharField(max_length=20, default="inbound")
    from_number = models.CharField(max_length=40, blank=True, default="")
    to_number = models.CharField(max_length=40, blank=True, default="")
    duration_seconds = models.PositiveIntegerField(default=0)
    outcome = models.CharField(
        max_length=30, choices=[(o.value, o.value) for o in CallOutcome], blank=True, default=""
    )
    failure_reason = models.CharField(max_length=255, blank=True, default="")
    transcript_reference = models.CharField(max_length=500, blank=True, default="")
    recording_reference = models.CharField(max_length=500, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "call_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "-created_at"], name="call_log_clinic_idx"),
            models.Index(fields=["clinic", "outcome"], name="call_log_outcome_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"call {self.provider_call_id} {self.outcome}"


class FollowUpTask(ClinicOwnedModel):
    """Work that a human must do.

    Tasks are created automatically when an interaction cannot be resolved
    by the assistant, and are deduplicated per triggering event so a retried
    webhook cannot create duplicates (FOL-06).
    """

    patient = models.ForeignKey(
        "appointments.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="follow_up_tasks",
    )
    related_appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="follow_up_tasks",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="follow_up_tasks",
    )
    task_type = models.CharField(
        max_length=40, choices=[(t.value, t.value) for t in FollowUpTaskType]
    )
    priority = models.CharField(
        max_length=20,
        choices=[(p.value, p.value) for p in TaskPriority],
        default=TaskPriority.NORMAL,
    )
    assigned_to = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_follow_up_tasks",
    )
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in TaskStatus],
        default=TaskStatus.OPEN,
        db_index=True,
    )
    resolution_reason = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    #: Stable key derived from the triggering event -- guarantees one task.
    dedupe_key = models.CharField(max_length=200, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "follow_up_tasks"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["clinic", "dedupe_key"], name="uniq_follow_up_dedupe")
        ]
        indexes = [
            models.Index(fields=["clinic", "status", "due_at"], name="task_queue_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.task_type} ({self.status})"


class NotificationLog(ClinicOwnedModel):
    """The delivery record for an outbound message."""

    patient = models.ForeignKey(
        "appointments.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    channel = models.CharField(max_length=20)
    template_id = models.CharField(max_length=80)
    provider_message_id = models.CharField(max_length=200, blank=True, default="")
    delivery_status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in DeliveryStatus],
        default=DeliveryStatus.QUEUED,
        db_index=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=200, unique=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "notification_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "delivery_status"], name="notification_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.channel}:{self.template_id} {self.delivery_status}"
