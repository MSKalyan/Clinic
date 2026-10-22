"""Follow-up task management.

Tasks are the safety net: anything the assistant could not resolve becomes a
durable, assignable piece of work rather than a lost request (PRD 4.6).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.constants import (
    FollowUpTaskType,
    InternalEventType,
    TaskPriority,
    TaskStatus,
)
from apps.core.models import OutboxEvent
from apps.conversations.models import FollowUpTask

logger = logging.getLogger("apps.conversations.followups")


class FollowUpService:
    """Create and resolve follow-up tasks."""

    @staticmethod
    def dedupe_key(*parts: object) -> str:
        """Stable key derived from the triggering event."""
        raw = "|".join(str(part) for part in parts if part is not None)
        return hashlib.sha256(raw.encode()).hexdigest()[:60]

    @classmethod
    def create_task(
        cls,
        *,
        clinic,
        task_type: str,
        dedupe_key: str,
        patient=None,
        related_appointment=None,
        conversation=None,
        priority: str = TaskPriority.NORMAL,
        due_in_minutes: int = 120,
        notes: str = "",
        assigned_to=None,
        max_attempts: int = 3,
    ) -> FollowUpTask:
        """Create a task, or return the existing one for this trigger.

        The unique ``(clinic, dedupe_key)`` constraint means a retried
        webhook or a duplicate provider event cannot create a second task.
        """
        now = timezone.now()
        defaults = {
            "patient": patient,
            "related_appointment": related_appointment,
            "conversation": conversation,
            "priority": priority,
            "assigned_to": assigned_to,
            "due_at": now + timedelta(minutes=due_in_minutes),
            "status": TaskStatus.OPEN,
            "notes": notes[:2000],
            "max_attempts": max_attempts,
        }
        try:
            with transaction.atomic():
                task = FollowUpTask.objects.create(
                    clinic=clinic,
                    task_type=task_type,
                    dedupe_key=dedupe_key,
                    **defaults,
                )
        except IntegrityError:
            existing = FollowUpTask.objects.filter(
                clinic=clinic, dedupe_key=dedupe_key
            ).first()
            if existing:
                logger.debug("follow-up task already exists for %s", dedupe_key)
                return existing
            raise

        OutboxEvent.objects.create(
            clinic=clinic,
            event_type=InternalEventType.FOLLOW_UP_CREATED,
            payload={
                "task_id": str(task.id),
                "task_type": task_type,
                "priority": priority,
            },
        )
        logger.info("follow-up task created clinic=%s type=%s", clinic.id, task_type)
        return task

    @staticmethod
    def resolve(
        task: FollowUpTask,
        *,
        resolution_reason: str = "",
        notes: str = "",
        actor=None,
    ) -> FollowUpTask:
        task.status = TaskStatus.RESOLVED
        task.resolution_reason = resolution_reason[:255]
        task.resolved_at = timezone.now()
        if notes:
            task.notes = notes[:2000]
        if getattr(actor, "pk", None):
            task.assigned_to = actor
        task.save(
            update_fields=[
                "status",
                "resolution_reason",
                "resolved_at",
                "notes",
                "assigned_to",
                "updated_at",
            ]
        )
        return task

    @staticmethod
    def decline(task: FollowUpTask, *, reason: str = "", actor=None) -> FollowUpTask:
        task.status = TaskStatus.DECLINED
        task.resolution_reason = reason[:255]
        task.resolved_at = timezone.now()
        if getattr(actor, "pk", None):
            task.assigned_to = actor
        task.save(
            update_fields=["status", "resolution_reason", "resolved_at", "assigned_to", "updated_at"]
        )
        return task

    @staticmethod
    def escalate(task: FollowUpTask, *, reason: str = "", priority: str = TaskPriority.URGENT) -> FollowUpTask:
        task.priority = priority
        task.status = TaskStatus.OPEN
        task.notes = (task.notes + f"\nEscalated: {reason}").strip()[:2000]
        task.save(update_fields=["priority", "status", "notes", "updated_at"])
        return task


def task_type_for_call_outcome(outcome: str) -> str:
    """Map a call outcome to the follow-up task it should create."""
    if outcome in {"unresolved", "abandoned", "escalated"}:
        return FollowUpTaskType.UNRESOLVED_REQUEST
    return FollowUpTaskType.MISSED_CALL
