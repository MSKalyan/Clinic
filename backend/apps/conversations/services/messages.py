"""Write outbound turns into the patient's conversation thread."""
from __future__ import annotations

import uuid
from typing import Any

from django.utils import timezone

from apps.core.constants import Channel
from apps.realtime.broadcast import conversation_changed


def outbound_conversation(
    clinic,
    patient,
    *,
    chat_id: str,
    language: str = "",
) -> Any | None:
    """Return (creating if needed) the WhatsApp conversation for a patient."""
    from apps.conversations.models import Conversation

    conversation, _created = Conversation.objects.get_or_create(
        clinic=clinic,
        patient=patient,
        channel=Channel.WHATSAPP,
        provider_conversation_id=chat_id,
        defaults={
            "language": language or patient.preferred_language,
            "summary": f"WhatsApp with {patient.name or 'patient'}",
            "started_at": timezone.now(),
        },
    )
    return conversation


def record_outbound(
    clinic,
    patient,
    body: str,
    provider_message_id: str = "",
    *,
    conversation: Any | None = None,
    chat_id: str = "",
) -> tuple[Any | None, Any | None]:
    """Store one outbound turn and publish it to the live thread.

    Returns ``(conversation, message)``. The pair can be ``(None, None)`` when
    the text could not be stored; delivery itself is never affected by that.
    """
    from apps.conversations.models import ConversationMessage

    if conversation is None and patient is not None:
        if not chat_id:
            from apps.integrations.providers.waha import phone_to_chat_id

            chat_id = phone_to_chat_id(patient.phone) or ""
        if chat_id:
            conversation = outbound_conversation(clinic, patient, chat_id=chat_id)
    if conversation is None:
        return None, None

    message, _created = ConversationMessage.objects.get_or_create(
        clinic=clinic,
        conversation=conversation,
        direction="outbound",
        # Provider ids (notably WAHA's) can exceed this column's 200 chars;
        # truncate so a successful send is never lost to a DB error.
        provider_message_id=(provider_message_id or f"local:{uuid.uuid4()}")[:200],
        defaults={"message_type": "text", "excerpt": body[:280]},
    )
    conversation_changed(
        clinic.id,
        conversation.id,
        "message",
        message={
            "id": str(message.id),
            "direction": "outbound",
            "message_type": message.message_type,
            "excerpt": message.excerpt,
            "created_at": message.created_at.isoformat(),
        },
    )
    return conversation, message
