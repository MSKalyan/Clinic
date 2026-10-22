"""Booking, rescheduling and cancellation.

This is the single service used by *both* the phone agent and the WhatsApp
assistant (PRD 4.2), so there is exactly one definition of "booked".

Integrity guarantees:

* the doctor row is locked for the duration of the transaction, so two
  simultaneous requests for the same doctor serialise;
* availability is re-checked inside the transaction;
* a PostgreSQL exclusion constraint is the final backstop, so even a bug in
  the service layer cannot create two overlapping confirmed appointments;
* an idempotency key makes retries safe.
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentEvent, Patient
from apps.appointments.services.availability import AvailabilityService
from apps.core.constants import (
    AppointmentStatus,
    BookingSource,
    InternalEventType,
)
from apps.core.exceptions import DomainError, InvalidTransition, SlotUnavailable
from apps.core.models import IdempotencyRecord, OutboxEvent

logger = logging.getLogger("apps.appointments.booking")

_REFERENCE_ALPHABET = string.ascii_uppercase + string.digits


def generate_reference() -> str:
    """A short, human-readable appointment reference."""
    while True:
        suffix = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(6))
        reference = f"APT{suffix}"
        if not Appointment.objects.filter(reference=reference).exists():
            return reference


class BookingService:
    """Transactional appointment operations."""

    # ------------------------------------------------------------------
    # Book
    # ------------------------------------------------------------------
    @classmethod
    def book(
        cls,
        *,
        clinic,
        doctor,
        patient,
        start_at: datetime,
        source: str = BookingSource.API,
        duration_minutes: int | None = None,
        notes: str = "",
        idempotency_key: str | None = None,
        actor=None,
        actor_type: str = "system",
        reference: str | None = None,
    ) -> Appointment:
        if timezone.is_naive(start_at):
            raise DomainError("Appointment start must be timezone aware.")

        existing = cls._replay(idempotency_key, clinic)
        if existing is not None:
            return existing

        if patient.clinic_id != clinic.id:
            raise DomainError("Patient does not belong to this clinic.", code="cross_tenant")

        duration = int(
            duration_minutes or clinic.appointment_rules()["appointment_duration_minutes"]
        )
        end_at = start_at + timedelta(minutes=duration)

        try:
            with transaction.atomic():
                # Serialise bookings for this doctor.
                locked_doctor = type(doctor).objects.select_for_update().get(
                    pk=doctor.pk, clinic_id=clinic.id
                )

                availability = AvailabilityService(clinic)
                if not availability.is_slot_available(locked_doctor, start_at, duration):
                    raise SlotUnavailable(
                        "That appointment slot is no longer available.",
                        details={"start_at": start_at.isoformat()},
                    )

                appointment = Appointment.objects.create(
                    clinic=clinic,
                    doctor=locked_doctor,
                    patient=patient,
                    start_at=start_at,
                    end_at=end_at,
                    status=AppointmentStatus.BOOKED,
                    booking_source=source,
                    reference=reference or generate_reference(),
                    notes=notes[:2000],
                )
                cls._record_event(
                    clinic=clinic,
                    appointment=appointment,
                    event_type="booked",
                    actor_type=actor_type,
                    actor=actor,
                    payload={
                        "source": source,
                        "start_at": start_at.isoformat(),
                        "end_at": end_at.isoformat(),
                    },
                )
                OutboxEvent.objects.create(
                    clinic=clinic,
                    event_type=InternalEventType.APPOINTMENT_BOOKED,
                    payload={
                        "appointment_id": str(appointment.id),
                        "reference": appointment.reference,
                        "doctor_id": str(appointment.doctor_id),
                        "patient_id": str(appointment.patient_id),
                        "start_at": start_at.isoformat(),
                        "end_at": end_at.isoformat(),
                        "source": source,
                    },
                )
                cls._remember(idempotency_key, clinic, "booking", appointment)
        except IntegrityError as exc:
            # The exclusion constraint fired: someone else took the slot.
            logger.info("booking conflict for doctor=%s start=%s: %s", doctor.id, start_at, exc)
            raise SlotUnavailable(
                "That appointment slot was just taken. Please choose another time.",
                details={"start_at": start_at.isoformat()},
            ) from exc

        logger.info(
            "appointment booked clinic=%s ref=%s doctor=%s start=%s",
            clinic.id,
            appointment.reference,
            appointment.doctor_id,
            appointment.start_at,
        )
        return appointment

    # ------------------------------------------------------------------
    # Reschedule
    # ------------------------------------------------------------------
    @classmethod
    def reschedule(
        cls,
        *,
        appointment: Appointment,
        new_start_at: datetime,
        actor=None,
        actor_type: str = "system",
        duration_minutes: int | None = None,
        notes: str = "",
    ) -> Appointment:
        if timezone.is_naive(new_start_at):
            raise DomainError("Appointment start must be timezone aware.")

        clinic = appointment.clinic
        try:
            with transaction.atomic():
                locked = (
                    Appointment.objects.select_for_update()
                    .select_related("doctor", "patient", "clinic")
                    .get(pk=appointment.pk)
                )
                if locked.status not in {
                    AppointmentStatus.BOOKED,
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.RESCHEDULE_PENDING,
                }:
                    raise InvalidTransition(
                        f"Cannot reschedule an appointment that is {locked.status}."
                    )

                type(locked.doctor).objects.select_for_update().get(pk=locked.doctor_id)

                duration = int(
                    duration_minutes
                    or clinic.appointment_rules()["appointment_duration_minutes"]
                )
                new_end_at = new_start_at + timedelta(minutes=duration)

                availability = AvailabilityService(clinic)
                if not availability.is_slot_available(
                    locked.doctor, new_start_at, duration, ignore_appointment_id=locked.id
                ):
                    raise SlotUnavailable(
                        "The new time is no longer available.",
                        details={"start_at": new_start_at.isoformat()},
                    )

                previous_start = locked.start_at
                locked.start_at = new_start_at
                locked.end_at = new_end_at
                if notes:
                    locked.notes = notes[:2000]
                locked.save(update_fields=["start_at", "end_at", "notes", "updated_at"])

                cls._record_event(
                    clinic=clinic,
                    appointment=locked,
                    event_type="rescheduled",
                    actor_type=actor_type,
                    actor=actor,
                    payload={
                        "previous_start_at": previous_start.isoformat(),
                        "new_start_at": new_start_at.isoformat(),
                        "new_end_at": new_end_at.isoformat(),
                    },
                )
                OutboxEvent.objects.create(
                    clinic=clinic,
                    event_type=InternalEventType.APPOINTMENT_RESCHEDULED,
                    payload={
                        "appointment_id": str(locked.id),
                        "reference": locked.reference,
                        "doctor_id": str(locked.doctor_id),
                        "patient_id": str(locked.patient_id),
                        "previous_start_at": previous_start.isoformat(),
                        "start_at": new_start_at.isoformat(),
                    },
                )
        except IntegrityError as exc:
            raise SlotUnavailable(
                "The new time was just taken. Please choose another time.",
                details={"start_at": new_start_at.isoformat()},
            ) from exc
        return locked

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------
    @classmethod
    def cancel(
        cls,
        *,
        appointment: Appointment,
        reason: str = "",
        actor=None,
        actor_type: str = "system",
        force: bool = False,
    ) -> Appointment:
        clinic = appointment.clinic
        with transaction.atomic():
            locked = (
                Appointment.objects.select_for_update()
                .select_related("doctor", "patient", "clinic")
                .get(pk=appointment.pk)
            )
            if not locked.can_transition_to(AppointmentStatus.CANCELLED):
                raise InvalidTransition(
                    f"Cannot cancel an appointment that is {locked.status}."
                )

            window_hours = int(
                clinic.appointment_rules().get("cancellation_window_hours", 0)
            )
            if window_hours and not force:
                cutoff = locked.start_at - timedelta(hours=window_hours)
                if timezone.now() > cutoff:
                    raise DomainError(
                        "Appointments can only be cancelled up to "
                        f"{window_hours} hours before the scheduled time.",
                        code="cancellation_window_passed",
                        details={
                            "window_hours": window_hours,
                            "start_at": locked.start_at.isoformat(),
                        },
                    )

            locked.status = AppointmentStatus.CANCELLED
            locked.cancellation_reason = (reason or "")[:255]
            locked.cancelled_by = actor if getattr(actor, "pk", None) else None
            locked.save(
                update_fields=[
                    "status",
                    "cancellation_reason",
                    "cancelled_by",
                    "updated_at",
                ]
            )

            cls._record_event(
                clinic=clinic,
                appointment=locked,
                event_type="cancelled",
                actor_type=actor_type,
                actor=actor,
                payload={"reason": locked.cancellation_reason},
            )
            OutboxEvent.objects.create(
                clinic=clinic,
                event_type=InternalEventType.APPOINTMENT_CANCELLED,
                payload={
                    "appointment_id": str(locked.id),
                    "reference": locked.reference,
                    "doctor_id": str(locked.doctor_id),
                    "patient_id": str(locked.patient_id),
                    "start_at": locked.start_at.isoformat(),
                    "reason": locked.cancellation_reason,
                },
            )
        return locked

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _record_event(
        *,
        clinic,
        appointment: Appointment,
        event_type: str,
        actor_type: str,
        actor,
        payload: dict[str, Any],
    ) -> None:
        AppointmentEvent.objects.create(
            clinic=clinic,
            appointment=appointment,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=str(getattr(actor, "id", "")) if actor is not None else "",
            event_payload=payload,
        )

    @staticmethod
    def _replay(idempotency_key: str | None, clinic) -> Appointment | None:
        if not idempotency_key:
            return None
        record = IdempotencyRecord.objects.filter(
            clinic=clinic, scope="booking", key=idempotency_key
        ).first()
        if not record:
            return None
        appointment_id = (record.response or {}).get("appointment_id")
        if not appointment_id:
            return None
        return Appointment.objects.filter(pk=appointment_id).first()

    @staticmethod
    def _remember(
        idempotency_key: str | None, clinic, scope: str, appointment: Appointment
    ) -> None:
        if not idempotency_key:
            return
        IdempotencyRecord.objects.update_or_create(
            clinic=clinic,
            scope=scope,
            key=idempotency_key,
            defaults={"response": {"appointment_id": str(appointment.id)}},
        )


def get_or_create_patient(
    *, clinic, phone: str, name: str = "", preferred_language: str = ""
) -> tuple[Patient, bool]:
    """Find or create a patient by phone number inside a clinic."""
    from apps.core.utils import normalise_phone

    normalised = normalise_phone(phone)
    if not normalised:
        raise DomainError("A phone number is required to identify the patient.")

    patient = Patient.objects.filter(clinic=clinic, phone=normalised).first()
    if patient:
        changed = False
        if name and patient.name != name:
            patient.name = name
            changed = True
        if preferred_language and not patient.preferred_language:
            patient.preferred_language = preferred_language
            changed = True
        if changed:
            patient.save(update_fields=["name", "preferred_language", "updated_at"])
        return patient, False

    patient = Patient.objects.create(
        clinic=clinic,
        phone=normalised,
        name=name[:200],
        preferred_language=preferred_language,
    )
    return patient, True
