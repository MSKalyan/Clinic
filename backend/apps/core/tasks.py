"""Core background tasks (transactional outbox publisher)."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("apps.core.tasks")

MAX_PUBLISH_ATTEMPTS = 8


@shared_task(name="apps.core.tasks.publish_outbox")
def publish_outbox(limit: int = 100) -> dict[str, int]:
    """Publish pending outbox events to the internal event bus.

    The outbox guarantees that a committed database change is never lost
    because a broker was unavailable: the row stays ``pending`` until it has
    been delivered at least once.

    The sweep is done one tenant at a time: the database session is scoped
    to the clinic the event belongs to, so the publisher can never publish
    (or mark as published) another tenant's event.
    """
    from apps.core.models import OutboxEvent
    from apps.core.rls import iter_clinic_scopes

    published = 0
    failed = 0
    for clinic, _scope in iter_clinic_scopes():
        events = (
            OutboxEvent.objects.filter(clinic=clinic, status="pending")
            .order_by("created_at")[:limit]
        )
        for event in events:
            try:
                _dispatch(event)
            except Exception as exc:  # pragma: no cover - depends on downstream
                failed += 1
                event.attempts += 1
                event.last_error = str(exc)[:2000]
                if event.attempts >= MAX_PUBLISH_ATTEMPTS:
                    event.status = "failed"
                event.save(update_fields=["attempts", "last_error", "status"])
                logger.warning("outbox event %s failed: %s", event.pk, exc)
            else:
                published += 1
                from django.utils import timezone

                event.status = "published"
                event.published_at = timezone.now()
                event.attempts += 1
                event.last_error = ""
                event.save(
                    update_fields=["status", "published_at", "attempts", "last_error"]
                )
    return {"published": published, "failed": failed}


def _dispatch(event) -> None:  # noqa: ANN001
    """Route an outbox event to its handler."""
    from apps.core.events import get_handler

    handler = get_handler(event.event_type)
    if handler is None:
        logger.info("no handler registered for %s", event.event_type)
        return
    handler(event)
