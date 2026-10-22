"""Webhook event processing.

The rules that keep this safe (PRD 10.6):

* the provider's signature is verified **before** anything is read;
* every accepted event is persisted with its provider event id, so a
  duplicate delivery is acknowledged but not re-applied;
* the clinic is resolved from *trusted routing metadata* (the number the
  patient dialled or the business number that received the message) -- never
  from the payload body.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.constants import (
    CallOutcome,
    Channel,
    ConversationStatus,
    DeliveryStatus,
    FollowUpTaskType,
    TaskPriority,
)
from apps.core.rls import rls_scope
from apps.core.utils import normalise_phone
from apps.integrations.models import ProviderEvent
from apps.integrations.providers.base import ProviderEvent as NormalisedEvent

logger = logging.getLogger("apps.integrations.webhooks")


class WebhookProcessingError(Exception):
    """Raised when a webhook cannot be processed."""


# ---------------------------------------------------------------------------
# Clinic resolution
# ---------------------------------------------------------------------------
def resolve_clinic_by_number(hint: str | None):
    """Find the clinic that owns a phone number.

    This is the trusted routing path: the number the patient dialled, or the
    business number that received the message.
    """
    if not hint:
        return None
    from apps.tenancy.models import ClinicChannelNumber

    candidates = {hint.strip()}
    normalised = normalise_phone(hint)
    if normalised:
        candidates.add(normalised)

    number = (
        ClinicChannelNumber.objects.select_related("clinic")
        .filter(routing_status="active")
        .filter(
            Q(external_number_id__in=candidates) | Q(display_number__in=candidates)
        )
        .first()
    )
    return number.clinic if number else None


# ---------------------------------------------------------------------------
# Event ingestion
# ---------------------------------------------------------------------------
def ingest_events(
    *,
    provider_type: str,
    events: list[NormalisedEvent],
    clinic=None,
) -> dict[str, Any]:
    """Persist and dispatch normalised provider events.

    Returns a summary the webhook endpoint can return to the provider.
    """
    summary = {"accepted": 0, "duplicates": 0, "processed": 0, "failed": 0}

    for event in events:
        resolved_clinic = clinic or resolve_clinic_by_number(event.clinic_hint)
        # The tenant comes from trusted routing metadata, never from the
        # payload. Once it is known the database session is scoped to it, so
        # the event and everything it creates stay inside that tenant.
        scope = str(resolved_clinic.id) if resolved_clinic else ""
        with rls_scope(scope):
            try:
                # The savepoint matters: a duplicate delivery must not poison
                # an enclosing transaction (a Celery task, or a test) -- only
                # this insert is rolled back.
                with transaction.atomic():
                    stored = ProviderEvent.objects.create(
                        provider_type=event.provider_type,
                        provider_event_id=event.provider_event_id,
                        event_type=event.event_type,
                        clinic=resolved_clinic,
                        payload=event.payload,
                        status="received",
                    )
            except IntegrityError:
                summary["duplicates"] += 1
                logger.info(
                    "duplicate provider event ignored: %s:%s",
                    event.provider_type,
                    event.provider_event_id,
                )
                continue

            summary["accepted"] += 1
            if resolved_clinic is None:
                stored.status = "unrouted"
                stored.error = "Could not resolve the clinic for this event."
                stored.save(update_fields=["status", "error"])
                logger.warning(
                    "provider event %s could not be routed to a clinic",
                    stored.provider_event_id,
                )
                continue

            try:
                dispatch(stored)
            except Exception as exc:  # pragma: no cover - defensive
                summary["failed"] += 1
                stored.status = "failed"
                stored.error = str(exc)[:2000]
                stored.save(update_fields=["status", "error"])
                logger.exception("failed to process provider event %s", stored.pk)
            else:
                summary["processed"] += 1
                stored.status = "processed"
                stored.processed_at = timezone.now()
                stored.save(update_fields=["status", "processed_at"])

    return summary


def dispatch(stored: ProviderEvent) -> None:
    """Route a stored event to its handler."""
    handler = HANDLERS.get((stored.provider_type, stored.event_type))
    if handler is None:
        handler = HANDLERS.get((stored.provider_type, "*"))
    if handler is None:
        logger.info("no handler for %s:%s", stored.provider_type, stored.event_type)
        return
    handler(stored)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def handle_voice_call_completed(stored: ProviderEvent) -> None:
    """Record a finished voice call and raise follow-up work if unresolved."""
    from apps.conversations.models import CallLog, Conversation
    from apps.conversations.services.followups import FollowUpService
    from apps.integrations.providers.sarvam import SarvamVoiceAdapter
    from apps.usage.services import UsageMeter

    payload = stored.payload or {}
    clinic = stored.clinic
    interaction_id = payload.get("interaction_id", stored.provider_event_id)
    outcome_info = SarvamVoiceAdapter.extract_outcome(payload)
    transcript = SarvamVoiceAdapter.extract_transcript(payload)

    conversation = Conversation.objects.create(
        clinic=clinic,
        channel=Channel.VOICE,
        provider_conversation_id=str(interaction_id),
        status=ConversationStatus.COMPLETED,
        outcome=outcome_info.get("call_outcome") or CallOutcome.RESOLVED,
        summary=_summarise(transcript),
        started_at=_parse(payload.get("start_datetime")),
        ended_at=_parse(payload.get("end_datetime")),
    )

    duration = int(float(payload.get("duration") or 0))
    call_log = CallLog.objects.create(
        clinic=clinic,
        conversation=conversation,
        provider_call_id=str(interaction_id),
        direction="inbound",
        from_number=str(payload.get("user_phone_number") or ""),
        to_number=str(payload.get("agent_phone_number") or ""),
        duration_seconds=duration,
        outcome=outcome_info.get("call_outcome") or CallOutcome.RESOLVED,
        started_at=_parse(payload.get("start_datetime")),
        ended_at=_parse(payload.get("end_datetime")),
    )

    UsageMeter.record(
        clinic=clinic,
        event_type="voice_minutes",
        quantity=round(duration / 60, 4),
        unit="minutes",
        idempotency_key=f"voice:{interaction_id}",
    )

    unresolved = outcome_info.get("follow_up_required") or outcome_info.get(
        "call_outcome"
    ) in {"unresolved", "busy_callback", "abandoned", "no_answer"}

    if unresolved:
        FollowUpService.create_task(
            clinic=clinic,
            task_type=FollowUpTaskType.UNRESOLVED_REQUEST,
            dedupe_key=FollowUpService.dedupe_key("voice", interaction_id),
            conversation=conversation,
            priority=TaskPriority.NORMAL,
            due_in_minutes=60,
            notes="The voice assistant could not fully resolve the request.",
        )
        conversation.status = ConversationStatus.ESCALATED
        conversation.save(update_fields=["status", "updated_at"])
        call_log.outcome = CallOutcome.ESCALATED
        call_log.save(update_fields=["outcome"])


def handle_whatsapp_message(stored: ProviderEvent) -> None:
    """Open a WhatsApp conversation for an inbound patient message."""
    from apps.conversations.models import Conversation
    from apps.integrations.providers.whatsapp import WhatsAppCloudAdapter

    payload = stored.payload or {}
    clinic = stored.clinic
    sender = WhatsAppCloudAdapter.extract_sender(payload)
    text = WhatsAppCloudAdapter.extract_text(payload)
    message_id = stored.provider_event_id

    conversation = (
        Conversation.objects.filter(
            clinic=clinic,
            channel=Channel.WHATSAPP,
            provider_conversation_id=str(message_id),
        ).first()
    )
    if conversation is None:
        conversation = Conversation.objects.create(
            clinic=clinic,
            channel=Channel.WHATSAPP,
            provider_conversation_id=str(message_id),
            status=ConversationStatus.OPEN,
        )

    from apps.conversations.models import ConversationMessage

    ConversationMessage.objects.get_or_create(
        clinic=clinic,
        conversation=conversation,
        provider_message_id=str(message_id),
        defaults={
            "direction": "inbound",
            "message_type": "text",
            "excerpt": text[:280],
        },
    )
    return conversation


def handle_whatsapp_status(stored: ProviderEvent) -> None:
    """Update the delivery status of a notification we sent earlier."""
    from apps.conversations.models import NotificationLog

    payload = stored.payload or {}
    status_payload = payload.get("status", {}) or {}
    provider_message_id = str(status_payload.get("id", ""))
    status = str(status_payload.get("status", "")).lower()

    mapping = {
        "sent": DeliveryStatus.SENT,
        "delivered": DeliveryStatus.DELIVERED,
        "read": DeliveryStatus.READ,
        "failed": DeliveryStatus.FAILED,
        "expired": DeliveryStatus.EXPIRED,
    }
    target = mapping.get(status)
    if target is None:
        return

    updated = NotificationLog.objects.filter(
        provider_message_id=provider_message_id
    ).update(delivery_status=target, delivered_at=timezone.now() if target == DeliveryStatus.DELIVERED else None)

    if updated and target == DeliveryStatus.FAILED:
        logger.info("notification %s failed delivery", provider_message_id)


def handle_telephony_event(stored: ProviderEvent) -> None:
    """Record a telephony call event."""
    from apps.conversations.models import CallLog

    payload = stored.payload or {}
    from apps.integrations.providers.telephony import TelephonyAdapter

    CallLog.objects.update_or_create(
        clinic=stored.clinic,
        provider_call_id=stored.provider_event_id,
        defaults={
            "direction": "inbound",
            "from_number": str(payload.get("From") or payload.get("from") or ""),
            "to_number": str(payload.get("To") or payload.get("to") or ""),
            "duration_seconds": TelephonyAdapter.extract_duration(payload),
            "outcome": CallOutcome.UNRESOLVED,
            "started_at": _parse(payload.get("CallStartTime") or payload.get("start_time")),
        },
    )


HANDLERS: dict[tuple[str, str], Any] = {
    ("sarvam", "call.completed"): handle_voice_call_completed,
    ("whatsapp", "message.received"): handle_whatsapp_message,
    ("whatsapp", "message.status"): handle_whatsapp_status,
    ("telephony", "call.inbound"): handle_telephony_event,
    ("telephony", "call.answered"): handle_telephony_event,
    ("telephony", "call.completed"): handle_telephony_event,
    ("telephony", "call.failed"): handle_telephony_event,
    ("telephony", "call.no_answer"): handle_telephony_event,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse(value: str | None):
    from datetime import datetime, timezone as dt_timezone

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def _summarise(transcript: list[dict[str, str]]) -> str:
    """A short operational summary. No full transcript is retained here."""
    if not transcript:
        return ""
    parts = [f"{turn['role']}: {turn['text']}" for turn in transcript if turn.get("text")]
    return " | ".join(parts)[:1000]
