"""Transactional WhatsApp messages for appointment lifecycle changes.

Booking, rescheduling and cancellation are the single source of truth in
:class:`~apps.appointments.services.booking.BookingService`. This module is the
single place that turns one of those changes into a patient-facing WhatsApp
text using the shared message templates. It deliberately never raises: a
messaging failure must not undo an appointment that has already been written.
"""
from __future__ import annotations

import logging
from typing import Any

from apps.conversations.services.templates import render_template
from apps.core.constants import Channel, ConsentPurpose, DeliveryStatus
from apps.core.exceptions import ConsentRequired, OptedOut
from apps.core.rls import rls_scope
from apps.core.timeutils import to_clinic_local

logger = logging.getLogger("apps.appointments.whatsapp")

KINDS = ("booked", "rescheduled", "cancelled")


def render_message(appointment: Any, kind: str, *, reason: str = "") -> str:
    """Build the patient-facing text for one appointment lifecycle event."""
    clinic = appointment.clinic
    patient = appointment.patient
    when = to_clinic_local(appointment.start_at, clinic).strftime("%a, %d %b %Y at %I:%M %p")
    context = {
        "patient_name": patient.name or "there",
        "clinic_name": clinic.name,
        "reference": appointment.reference,
        "doctor_name": appointment.doctor.name,
        "when": when,
        "timezone": clinic.timezone or "local time",
        "kind": kind,
        "reason": reason,
    }
    text = render_template(kind, context)
    if kind == "cancelled" and reason:
        text = f"{text}\nReason: {reason[:255]}"
    return text


def send_appointment_message(
    appointment: Any,
    kind: str,
    *,
    reason: str = "",
    event_id: str | None = None,
) -> Any | None:
    """Queue one WhatsApp confirmation and return its ``NotificationLog``.

    Returns ``None`` when the message was skipped (unknown event, missing
    patient, opt-out, provider failure). Never raises.

    ``event_id`` is the immutable id of the appointment lifecycle event that
    caused this message. Using it (rather than mutable status/time fields) as
    the idempotency key means a retry after a status change cannot send the
    same confirmation twice, while a genuine reschedule still gets its own.
    """
    from apps.appointments.models import Appointment
    from apps.conversations.services.notifications import NotificationService

    clinic_id = str(getattr(appointment, "clinic_id", "") or "")
    if not clinic_id or kind not in KINDS:
        return None

    # on_commit callbacks run after the request has cleared its tenant scope,
    # so the tenant context has to be re-established here.
    with rls_scope(clinic_id):
        try:
            current = Appointment.objects.select_related(
                "patient", "doctor", "clinic"
            ).get(pk=appointment.pk)
        except Appointment.DoesNotExist:  # pragma: no cover - deleted between commit and callback
            return None

        if kind != "cancelled" and current.status == "cancelled":
            logger.info("skipping WhatsApp %s message for cancelled %s", kind, current.reference)
            return None

        body = render_message(current, kind, reason=reason)
        anchor = event_id or f"{current.pk}:{kind}:{current.start_at.isoformat()}:{current.status}"
        idempotency_key = f"waha-appointment:{anchor}"
        try:
            log = NotificationService.send(
                clinic=current.clinic,
                patient=current.patient,
                channel=Channel.WHATSAPP,
                template_id=f"appointment_{kind}",
                body=body,
                appointment=current,
                purpose=ConsentPurpose.APPOINTMENT_TRANSACTIONAL,
                idempotency_key=idempotency_key,
                payload={"kind": kind, "reference": current.reference},
            )
        except (ConsentRequired, OptedOut) as exc:
            logger.info("WhatsApp %s message skipped for %s: %s", kind, current.reference, exc)
            return None
        except Exception:  # pragma: no cover - provider dependent
            logger.exception("could not send WhatsApp %s message for %s", kind, current.reference)
            return None

        if log.delivery_status == DeliveryStatus.QUEUED:
            logger.info("queued WhatsApp %s message for %s", kind, current.reference)
        return log
