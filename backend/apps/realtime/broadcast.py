"""Server-side helpers for publishing real-time events.

These functions are safe to call from a web request, an ``on_commit`` callback
or a Celery task. A missing/broken channel layer must never break the business
operation that produced the event.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger("apps.realtime.broadcast")


def publish(
    clinic_id,
    event: str,
    data: dict | None = None,
    *,
    conversation_id=None,
) -> None:
    """Publish an event to the clinic dashboard/list and optionally a thread."""
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        # Group names must match [a-zA-Z0-9_.-]+ on both channel-layer backends.
        groups = [f"clinic_{clinic_id}_dashboard"]
        if event.startswith("conversation."):
            groups.append(f"clinic_{clinic_id}_conversations")
        if conversation_id is not None:
            groups.append(f"conversation_{conversation_id}")
        message = {
            "type": "realtime.event",
            "event": event,
            "data": data or {},
            "at": timezone.now().isoformat(),
        }
        for group in groups:
            async_to_sync(layer.group_send)(group, message)
    except Exception:  # pragma: no cover - realtime is best-effort
        logger.exception("could not publish realtime event %s", event)


def dashboard_changed(clinic_id, reason: str, **data) -> None:
    publish(clinic_id, "dashboard.changed", {"reason": reason, **data})


def conversation_changed(
    clinic_id,
    conversation_id,
    reason: str,
    *,
    message: dict | None = None,
    conversation: dict | None = None,
) -> None:
    payload: dict = {"reason": reason}
    if message is not None:
        payload["message"] = message
    if conversation is not None:
        payload["conversation"] = conversation
    publish(
        clinic_id,
        f"conversation.{reason}",
        payload,
        conversation_id=conversation_id,
    )
