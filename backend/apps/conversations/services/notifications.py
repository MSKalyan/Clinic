"""Outbound notification dispatch with consent checks and idempotency.

Writing the ``NotificationLog`` row is cheap and idempotent; talking to a
provider is slow. The request path only does the former and queues the latter,
so a slow WAHA/Meta API can never make the dashboard feel slow.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.conversations.models import NotificationLog
from apps.core.constants import ConsentPurpose, ConsentStatus, DeliveryStatus
from apps.core.exceptions import ConsentRequired, OptedOut

logger = logging.getLogger("apps.conversations.notifications")


class NotificationService:
    """Record transactional messages and hand delivery to a worker."""

    @staticmethod
    def assert_can_contact(clinic, patient, channel: str, purpose: str) -> None:
        """Raise if the patient has not permitted this channel/purpose.

        Transactional messages (welcome, confirmations, reminders) are
        necessary communication, but an explicit opt-out or withdrawn consent
        always wins.
        """
        if patient is None:
            raise ConsentRequired("No patient record for this message.")

        if not patient.prefers(channel):
            raise OptedOut(f"The patient has opted out of {channel} messages.")

        consent = (
            patient.consents.filter(purpose=purpose, channel=channel)
            .order_by("-captured_at")
            .first()
        )
        if consent and consent.consent_status == ConsentStatus.WITHDRAWN:
            raise OptedOut(f"Consent for {channel} has been withdrawn.")

        if consent and consent.consent_status == ConsentStatus.GRANTED:
            return

        if purpose == ConsentPurpose.MARKETING:
            raise ConsentRequired(
                f"No recorded marketing consent for {channel}.",
                details={"purpose": purpose, "channel": channel},
            )

    @classmethod
    def send(
        cls,
        *,
        clinic,
        patient,
        channel: str,
        template_id: str,
        body: str = "",
        appointment=None,
        purpose: str = ConsentPurpose.APPOINTMENT_TRANSACTIONAL,
        idempotency_key: str | None = None,
        provider_message_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> NotificationLog:
        """Insert one idempotent notification row and queue its delivery.

        A retry with the same key returns the existing row without dispatching
        a second message.
        """
        if patient is not None:
            cls.assert_can_contact(clinic, patient, channel, purpose)
        # A staff reply to an unlinked WhatsApp chat has no patient row; the
        # view already checked that the sender is an authenticated clinic
        # member, so consent is not applicable there.
        key = idempotency_key or f"{clinic.id}:{template_id}:{appointment.id if appointment else ''}"

        try:
            # A savepoint keeps a duplicate from poisoning an enclosing
            # transaction: only this insert is rolled back.
            with transaction.atomic():
                log = NotificationLog.objects.create(
                    clinic=clinic,
                    patient=patient,
                    appointment=appointment,
                    channel=channel,
                    template_id=template_id,
                    idempotency_key=key,
                    delivery_status=DeliveryStatus.QUEUED,
                    attempt_count=1,
                    provider_message_id=str(provider_message_id or "")[:200],
                )
        except IntegrityError:
            existing = NotificationLog.objects.filter(idempotency_key=key).first()
            if existing:
                return existing
            raise

        cls._queue(log, body, payload or {})
        return log

    @staticmethod
    def _queue(log: NotificationLog, body: str, payload: dict[str, Any]) -> None:
        if not getattr(settings, "AUTOMATED_MESSAGING_ENABLED", True):
            logger.info("automated messaging paused; skipping notification %s", log.id)
            return
        from apps.conversations.tasks import dispatch_notification

        args = (str(log.id), body, payload)
        if getattr(settings, "MESSAGES_ASYNC", True):

            def enqueue() -> None:
                try:
                    dispatch_notification.delay(*args)
                except Exception:
                    logger.exception("could not enqueue notification %s for delivery", log.id)
                    NotificationService.mark_failed(log, "Could not enqueue delivery.")

            transaction.on_commit(enqueue)
        else:  # tests and single-process deployments
            dispatch_notification(*args)
            # The task loads its own row and marks it SENT; refresh the caller's
            # instance so `send()` returns the real final state.
            with contextlib.suppress(NotificationLog.DoesNotExist):
                log.refresh_from_db()

    @staticmethod
    def dispatch(
        *,
        clinic,
        patient,
        channel: str,
        template_id: str,
        body: str,
        appointment,
        payload: dict[str, Any],
    ) -> str:
        """Call the configured provider adapter and return its message id."""
        from apps.integrations.providers import get_messaging_provider

        provider = get_messaging_provider(clinic, channel)
        if provider is None:
            raise RuntimeError(f"No messaging provider configured for channel {channel}.")
        return str(
            provider.send_message(
                clinic=clinic,
                recipient_phone=patient.phone,
                template_id=template_id,
                body=body,
                appointment=appointment,
                payload=payload,
            )
            or ""
        )

    @staticmethod
    def mark_failed(log: NotificationLog, error: str) -> None:
        log.delivery_status = DeliveryStatus.FAILED
        log.last_error = str(error)[:2000]
        log.save(update_fields=["delivery_status", "last_error"])
