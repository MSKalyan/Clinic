"""Inbound WAHA message processing.

Every patient message is stored, linked to a patient when possible and pushed
to the live conversation thread. Each inbound message advances the WhatsApp
booking assistant by one step; duplicate webhook deliveries are ignored using
the provider message id, so a patient never receives a repeated bot reply.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.integrations.models import WahaMessageLog
from apps.integrations.providers.waha import IncomingWahaMessage, WahaAdapter

logger = logging.getLogger("apps.integrations.waha.flow")

_STORED_TEXT_LIMIT = 2000


def generate_auto_reply(text: str, clinic: Any | None = None) -> str:
    """Return the assistant's current menu (kept for API compatibility)."""
    from apps.integrations.services.bot_flow import _menu

    return _menu(clinic) if clinic is not None else ""


def _sanitise_for_storage(text: str) -> str:
    """Drop control characters and cap the stored excerpt."""
    cleaned = "".join(char for char in text if char in "\n\t" or ord(char) >= 32)
    return cleaned[:_STORED_TEXT_LIMIT]


def _empty_summary() -> dict[str, int]:
    return {
        "accepted": 0,
        "ignored": 0,
        "duplicates": 0,
        "linked": 0,
        "replied": 0,
        "skipped": 0,
        "failed": 0,
    }


def _find_patient_by_phone(phone: str):
    """Resolve a sender number to a patient, keeping tenant scoping explicit."""
    from apps.appointments.models import Patient
    from apps.core.rls import iter_clinic_scopes
    from apps.core.utils import normalise_phone

    normalised = normalise_phone(phone)
    if not normalised:
        return None, None
    for clinic, _scope in iter_clinic_scopes():
        patient = (
            Patient.objects.filter(clinic=clinic, phone=normalised, is_active=True)
            .order_by("-created_at")
            .first()
        )
        if patient is not None:
            return clinic, patient
    return None, None


def _attach_inbound_to_patient(stored: Any, incoming: IncomingWahaMessage):
    """Create a WhatsApp conversation for a known patient, if one exists."""
    from apps.conversations.models import Conversation, ConversationMessage
    from apps.core.constants import Channel
    from apps.core.rls import rls_scope
    from apps.realtime.broadcast import conversation_changed, dashboard_changed

    clinic, patient = _find_patient_by_phone(incoming.sender_phone)
    if patient is None:
        return None
    try:
        with rls_scope(str(clinic.id)):
            conversation, _created = Conversation.objects.get_or_create(
                clinic=clinic,
                patient=patient,
                channel=Channel.WHATSAPP,
                provider_conversation_id=incoming.chat_id,
                defaults={
                    "language": patient.preferred_language,
                    "summary": f"WhatsApp with {patient.name or 'patient'}",
                    "started_at": incoming.timestamp or timezone.now(),
                },
            )
            message, _created = ConversationMessage.objects.get_or_create(
                clinic=clinic,
                conversation=conversation,
                direction="inbound",
                # WAHA ids are often longer than this column's 200 chars.
                provider_message_id=incoming.message_id[:200],
                defaults={
                    "message_type": "text",
                    "excerpt": _sanitise_for_storage(incoming.text)[:280],
                },
            )
            conversation_changed(
                clinic.id,
                conversation.id,
                "message",
                message={
                    "id": str(message.id),
                    "direction": "inbound",
                    "message_type": "text",
                    "excerpt": message.excerpt,
                    "created_at": message.created_at.isoformat(),
                },
            )
            dashboard_changed(clinic.id, "conversation", conversation_id=str(conversation.id))
            return conversation
    except Exception:  # pragma: no cover - defensive; the message is still stored
        logger.exception("could not link WAHA message %s to a patient", incoming.message_id)
        return None


def send_auto_reply(log_id: int, chat_id: str, text: str) -> str:
    """Deliver one assistant prompt and write it into the thread."""
    from apps.conversations.services.messages import record_outbound
    from apps.core.rls import rls_scope
    from apps.integrations.services.waha import send_text_message

    if not getattr(settings, "AUTOMATED_MESSAGING_ENABLED", True):
        return "paused"

    try:
        stored = WahaMessageLog.objects.get(pk=log_id)
    except WahaMessageLog.DoesNotExist:  # pragma: no cover
        return "missing"

    try:
        result = send_text_message(chat_id, text)
    except Exception as exc:  # noqa: BLE001 - normalise every WAHA client error into a log row
        stored.status = WahaMessageLog.Status.FAILED
        stored.error = str(exc)[:2000]
        stored.save(update_fields=["status", "error"])
        return "failed"

    if not result.ok:
        stored.status = WahaMessageLog.Status.FAILED
        stored.error = (result.error or "")[:2000]
        stored.save(update_fields=["status", "error"])
        return "failed"

    provider_id = str((result.data or {}).get("id") or "")
    stored.status = WahaMessageLog.Status.REPLIED
    stored.reply_message_id = provider_id
    stored.save(update_fields=["status", "reply_message_id"])

    clinic, patient = _find_patient_by_phone(stored.sender_phone)
    if patient is not None:
        with rls_scope(str(clinic.id)):
            record_outbound(clinic, patient, text, provider_id, chat_id=chat_id)
    return "sent"


def process_webhook(payload: Any, *, adapter: WahaAdapter | None = None) -> dict[str, int]:
    """Validate, deduplicate and queue an incoming WAHA webhook payload."""
    adapter = adapter or _default_adapter()
    incoming = adapter.parse_incoming(payload)
    summary = _empty_summary()
    if incoming is None:
        summary["ignored"] = 1
        return summary
    return process_incoming(incoming)


def process_incoming(incoming: IncomingWahaMessage) -> dict[str, int]:
    """Persist one inbound message and queue the next assistant prompt."""
    summary = _empty_summary()
    try:
        with transaction.atomic():
            stored = WahaMessageLog.objects.create(
                message_id=incoming.message_id,
                session=incoming.session,
                sender_id=incoming.sender_id,
                sender_phone=incoming.sender_phone,
                text=_sanitise_for_storage(incoming.text),
                direction=WahaMessageLog.Direction.INBOUND,
                status=WahaMessageLog.Status.RECEIVED,
                timestamp=incoming.timestamp,
            )
    except IntegrityError:
        summary["duplicates"] += 1
        logger.info("duplicate WAHA message ignored: %s", incoming.message_id)
        return summary

    summary["accepted"] += 1
    conversation = _attach_inbound_to_patient(stored, incoming)
    if conversation is not None:
        summary["linked"] += 1

    if not getattr(settings, "AUTOMATED_MESSAGING_ENABLED", True):
        stored.status = WahaMessageLog.Status.SKIPPED
        stored.error = "Automated messaging is paused."
        stored.save(update_fields=["status", "error"])
        summary["skipped"] += 1
        return summary

    from apps.integrations.services.bot_flow import handle_incoming

    try:
        reply = handle_incoming(incoming)
    except Exception:  # pragma: no cover - defensive; the message stays logged
        logger.exception("WhatsApp assistant failed for message %s", incoming.message_id)
        stored.status = WahaMessageLog.Status.FAILED
        stored.error = "Assistant processing failed."
        stored.save(update_fields=["status", "error"])
        summary["failed"] += 1
        return summary

    if not reply:
        # No active flow and the message was not an exact "Hi": keep the log
        # row (and the back-office thread) but do not send anything.
        stored.status = WahaMessageLog.Status.SKIPPED
        stored.error = "Waiting for an exact 'Hi' to start a conversation."
        stored.save(update_fields=["status", "error"])
        summary["skipped"] += 1
        return summary

    stored.status = WahaMessageLog.Status.PENDING
    stored.save(update_fields=["status"])
    from apps.integrations.tasks import send_auto_reply_task

    args = (stored.pk, incoming.chat_id, reply)
    if getattr(settings, "MESSAGES_ASYNC", True):
        transaction.on_commit(lambda: send_auto_reply_task.delay(*args))
    else:
        send_auto_reply_task(*args)
    summary["replied"] += 1
    return summary


def _default_adapter() -> WahaAdapter:
    from apps.integrations.providers.registry import get_waha_adapter

    return get_waha_adapter()
