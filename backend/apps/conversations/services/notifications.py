"""Outbound notification dispatch with consent checks and idempotency."""
from __future__ import annotations

import logging
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.constants import ConsentPurpose, ConsentStatus, DeliveryStatus
from apps.core.exceptions import ConsentRequired, OptedOut
from apps.conversations.models import NotificationLog

logger = logging.getLogger("apps.conversations.notifications")


class NotificationService:
    """Send transactional messages and record the delivery attempt."""

    @staticmethod
    def assert_can_contact(clinic, patient, channel: str, purpose: str) -> None:  # noqa: ANN001
        """Raise if the patient has not permitted this channel/purpose.

        Transactional appointment messages (confirmations, reminders) are
        treated as necessary communication, but an explicit opt-out or a
        withdrawn consent always wins.
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
        """Record and dispatch a notification.

        The log row is written first (with a unique idempotency key) so a
        retried job can never double-send.
        """
        cls.assert_can_contact(clinic, patient, channel, purpose)
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
                )
        except IntegrityError:
            existing = NotificationLog.objects.filter(idempotency_key=key).first()
            if existing:
                return existing
            raise

        try:
            provider_message_id = cls._dispatch(
                clinic=clinic,
                patient=patient,
                channel=channel,
                template_id=template_id,
                body=body,
                appointment=appointment,
                payload=payload or {},
            )
            log.provider_message_id = provider_message_id
            log.delivery_status = DeliveryStatus.SENT
            log.sent_at = timezone.now()
            log.save(update_fields=["provider_message_id", "delivery_status", "sent_at"])
        except Exception as exc:  # pragma: no cover - provider dependent
            logger.warning("notification dispatch failed: %s", exc)
            log.delivery_status = DeliveryStatus.FAILED
            log.last_error = str(exc)[:2000]
            log.save(update_fields=["delivery_status", "last_error"])
        return log

    @staticmethod
    def _dispatch(
        *,
        clinic,
        patient,
        channel: str,
        template_id: str,
        body: str,
        appointment,
        payload: dict[str, Any],
    ) -> str:
        """Hand the message to the configured provider adapter."""
        from apps.integrations.providers import get_messaging_provider

        provider = get_messaging_provider(clinic, channel)
        if provider is None:
            raise RuntimeError(f"No messaging provider configured for channel {channel}.")
        return provider.send_message(
            clinic=clinic,
            recipient_phone=patient.phone,
            template_id=template_id,
            body=body,
            appointment=appointment,
            payload=payload,
        )
