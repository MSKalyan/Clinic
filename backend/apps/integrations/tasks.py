"""Background jobs for the WAHA integration."""
from __future__ import annotations

from celery import shared_task


@shared_task(
    name="apps.integrations.tasks.send_auto_reply_task",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def send_auto_reply_task(self, log_id: int, chat_id: str, text: str) -> str:  # noqa: ARG001
    """Send the one permitted acknowledgement without blocking the webhook."""
    from apps.integrations.services.waha_flow import send_auto_reply

    return send_auto_reply(log_id, chat_id, text)
