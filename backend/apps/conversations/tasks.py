"""Background triage for conversations and calls.

Anything the assistant could not resolve has to become durable, assignable
work rather than a lost request (PRD 4.6 / 12.4).

The provider webhook normally raises the follow-up task inline. This task is
the safety net for the cases where that did not happen: the webhook never
arrived, the provider reported no outcome, or the interaction was routed to
a telephony provider that only records the call.

The scan is idempotent: every task is keyed on the interaction it came from,
so running it twice creates nothing the second time.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.conversations.models import CallLog, Conversation, FollowUpTask
from apps.conversations.services.followups import FollowUpService
from apps.core.constants import (
    CallOutcome,
    Channel,
    ConversationStatus,
    FollowUpTaskType,
    InternalEventType,
    TaskPriority,
)
from apps.core.models import OutboxEvent

logger = logging.getLogger("apps.conversations.tasks")

#: A conversation that has been open this long without an outcome is stalled.
DEFAULT_STALE_CONVERSATION_MINUTES = 30

#: Call outcomes that must always end in a human task.
UNRESOLVED_OUTCOMES = frozenset(
    {
        CallOutcome.UNRESOLVED,
        CallOutcome.ABANDONED,
        CallOutcome.FAILED,
    }
)

#: How long a human has to pick the work up.
MISSED_CALL_DUE_MINUTES = 15
UNRESOLVED_DUE_MINUTES = 60


# ---------------------------------------------------------------------------
# Dedupe keys
# ---------------------------------------------------------------------------
def conversation_dedupe_key(conversation: Conversation) -> str:
    """The stable key for the follow-up raised by this conversation.

    For voice conversations this intentionally matches the key the webhook
    handler uses (``"voice"`` + provider interaction id) so the scan and the
    webhook can never produce two tasks for the same call.
    """
    channel = conversation.channel or "conversation"
    if channel == Channel.VOICE:
        channel = "voice"
    return FollowUpService.dedupe_key(
        channel,
        conversation.provider_conversation_id or str(conversation.id),
    )


def call_dedupe_key(call_log: CallLog) -> str:
    """The stable key for the follow-up raised by this call log."""
    if call_log.conversation_id:
        return conversation_dedupe_key(call_log.conversation)
    return FollowUpService.dedupe_key("call", call_log.provider_call_id)


def _task_exists(clinic, dedupe_key: str) -> bool:
    return FollowUpTask.objects.filter(clinic=clinic, dedupe_key=dedupe_key).exists()


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------
@shared_task(name="apps.conversations.tasks.scan_unresolved_calls")
def scan_unresolved_calls(
    limit: int = 200,
    stale_minutes: int = DEFAULT_STALE_CONVERSATION_MINUTES,
) -> dict[str, int]:
    """Create follow-up tasks for interactions that were never resolved.

    Three sources are scanned:

    1. calls that ended without a resolution (missed / failed calls);
    2. conversations the assistant escalated but for which no task exists;
    3. conversations left open past the staleness window.

    The sweep runs one tenant at a time so that a task can never be raised
    against another clinic's conversation.
    """
    from apps.core.rls import iter_clinic_scopes

    now = timezone.now()
    cutoff = now - timedelta(minutes=stale_minutes)

    created = 0
    skipped = 0
    inspected = 0

    for clinic, _scope in iter_clinic_scopes():
        if not clinic.escalation_policy().get("missed_call_follow_up", True):
            continue

        # --- 1. Unresolved / missed calls ---------------------------------
        calls = (
            CallLog.objects.select_related("clinic", "conversation")
            .filter(clinic=clinic)
            .filter(
                Q(outcome__in=list(UNRESOLVED_OUTCOMES))
                | Q(outcome="", duration_seconds=0)
            )
            .order_by("created_at")[:limit]
        )
        for call in calls:
            inspected += 1
            key = call_dedupe_key(call)
            if _task_exists(clinic, key):
                skipped += 1
                continue

            missed = call.conversation_id is None or call.duration_seconds == 0
            task_type = (
                FollowUpTaskType.MISSED_CALL if missed else FollowUpTaskType.UNRESOLVED_REQUEST
            )
            priority = TaskPriority.HIGH if missed else TaskPriority.NORMAL
            due_in = MISSED_CALL_DUE_MINUTES if missed else UNRESOLVED_DUE_MINUTES
            notes = (
                "Missed call -- please call the patient back."
                if missed
                else "The assistant could not fully resolve this interaction."
            )

            FollowUpService.create_task(
                clinic=clinic,
                task_type=task_type,
                dedupe_key=key,
                patient=call.conversation.patient if call.conversation_id else None,
                conversation=call.conversation,
                priority=priority,
                due_in_minutes=due_in,
                notes=notes,
            )
            OutboxEvent.objects.create(
                clinic=clinic,
                event_type=InternalEventType.CALL_UNRESOLVED,
                payload={
                    "call_log_id": str(call.pk),
                    "provider_call_id": call.provider_call_id,
                    "task_type": task_type,
                },
            )
            created += 1

        # --- 2 & 3. Escalated and stalled conversations --------------------
        conversations = (
            Conversation.objects.select_related("clinic", "patient")
            .filter(clinic=clinic)
            .filter(
                status__in=[
                    ConversationStatus.OPEN,
                    ConversationStatus.ESCALATED,
                    ConversationStatus.ABANDONED,
                ]
            )
            .exclude(channel=Channel.DASHBOARD)
            .filter(Q(ended_at__isnull=True) | Q(ended_at__lt=cutoff))
            .order_by("created_at")[:limit]
        )
        for conversation in conversations:
            inspected += 1
            key = conversation_dedupe_key(conversation)
            if _task_exists(clinic, key):
                skipped += 1
                continue

            escalated = conversation.status == ConversationStatus.ESCALATED
            if not escalated and conversation.created_at > cutoff:
                # Still inside the window -- the call may yet be resolved.
                skipped += 1
                continue

            FollowUpService.create_task(
                clinic=clinic,
                task_type=FollowUpTaskType.UNRESOLVED_REQUEST,
                dedupe_key=key,
                patient=conversation.patient,
                conversation=conversation,
                priority=TaskPriority.URGENT if escalated else TaskPriority.NORMAL,
                due_in_minutes=UNRESOLVED_DUE_MINUTES,
                notes=(
                    "Escalated by the assistant -- a human response is required."
                    if escalated
                    else "Conversation was left open with no outcome."
                ),
            )
            created += 1

    logger.info(
        "unresolved call scan complete: inspected=%s created=%s skipped=%s",
        inspected,
        created,
        skipped,
    )
    return {"inspected": inspected, "created": created, "skipped": skipped}


# ---------------------------------------------------------------------------
# Outbound delivery
# ---------------------------------------------------------------------------
@shared_task(
    name="apps.conversations.tasks.dispatch_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def dispatch_notification(self, log_id: str, body: str, payload: dict | None = None) -> str:
    """Perform the provider call for one queued notification.

    The row was written in the request, so this task is safe to retry: the
    idempotency key prevents a duplicate row and a completed send is a no-op.
    """
    from django.conf import settings

    from apps.conversations.models import NotificationLog
    from apps.conversations.services.messages import record_outbound
    from apps.conversations.services.notifications import NotificationService
    from apps.core.constants import DeliveryStatus
    from apps.core.rls import rls_scope

    try:
        log = NotificationLog.objects.select_related(
            "clinic", "patient", "appointment"
        ).get(pk=log_id)
    except NotificationLog.DoesNotExist:  # pragma: no cover - deleted record
        return "missing"

    if not getattr(settings, "AUTOMATED_MESSAGING_ENABLED", True):
        return "paused"

    if log.delivery_status in {DeliveryStatus.SENT, DeliveryStatus.DELIVERED}:
        return "already-sent"

    with rls_scope(str(log.clinic_id)):
        try:
            if log.patient_id is None and payload and payload.get("chat_id"):
                # A staff reply to an unlinked WhatsApp chat has no patient row.
                from apps.integrations.services.waha import send_text_message

                result = send_text_message(payload["chat_id"], body)
                if not result.ok:
                    raise RuntimeError(result.error or "WAHA could not send the message.")
                message_id = str((result.data or {}).get("id") or "")
            else:
                message_id = NotificationService.dispatch(
                    clinic=log.clinic,
                    patient=log.patient,
                    channel=log.channel,
                    template_id=log.template_id,
                    body=body,
                    appointment=log.appointment,
                    payload=payload or {},
                )
        except Exception as exc:
            logger.warning("notification %s dispatch failed: %s", log_id, exc)
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc) from exc
            NotificationService.mark_failed(log, exc)
            return "failed"

        # Provider ids are not guaranteed to be short (some gateways return a
        # long composite token). The log column is varchar(200); truncating the
        # id must never turn a successful send into a DataError.
        log.provider_message_id = str(message_id)[:200]
        log.delivery_status = DeliveryStatus.SENT
        log.sent_at = timezone.now()
        log.save(update_fields=["provider_message_id", "delivery_status", "sent_at"])

        if log.patient_id:
            try:
                record_outbound(log.clinic, log.patient, body, message_id)
            except Exception:  # pragma: no cover - must not undo a sent message
                logger.exception("could not record outbound turn for %s", log_id)
        return "sent"
