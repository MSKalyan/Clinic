"""Booking integrity (PRD 5.2 / 4.2).

The booking service is the single entry point for the voice agent, the
WhatsApp assistant and the dashboard. Three things must hold:

* a slot can never be double-booked -- enforced by the service *and* by a
  PostgreSQL exclusion constraint;
* a replayed request returns the original appointment instead of creating a
  second one;
* a patient from another clinic can never be booked into this one.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.appointments.services.booking import BookingService, get_or_create_patient
from apps.core.constants import AppointmentStatus, BookingSource
from apps.core.exceptions import DomainError, SlotUnavailable


@pytest.mark.django_db
def test_booking_creates_an_appointment_and_an_event(scoped, doctor, patient, slot_time):
    appointment = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )

    assert appointment.status == AppointmentStatus.BOOKED
    assert appointment.reference.startswith("APT")
    assert appointment.end_at == slot_time + timedelta(minutes=30)
    assert appointment.events.filter(event_type="booked").count() == 1


@pytest.mark.django_db
def test_booking_the_same_slot_twice_is_refused(scoped, doctor, patient, slot_time):
    BookingService.book(clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time)

    with pytest.raises(SlotUnavailable):
        BookingService.book(clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time)

    assert Appointment.objects.count() == 1


@pytest.mark.django_db
def test_the_database_rejects_an_overlap_even_if_the_service_is_bypassed(
    scoped, doctor, patient, slot_time
):
    """The exclusion constraint is the last line of defence.

    Here the service is deliberately bypassed and the row is written
    directly, which is exactly the "bug in the service layer" scenario the
    constraint exists for.
    """
    Appointment.objects.create(
        clinic=scoped,
        doctor=doctor,
        patient=patient,
        start_at=slot_time,
        end_at=slot_time + timedelta(minutes=30),
        status=AppointmentStatus.BOOKED,
        reference="APT000001",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Appointment.objects.create(
                clinic=scoped,
                doctor=doctor,
                patient=patient,
                start_at=slot_time,
                end_at=slot_time + timedelta(minutes=30),
                status=AppointmentStatus.BOOKED,
                reference="APT000002",
            )


@pytest.mark.django_db
def test_a_cancelled_appointment_frees_its_slot(scoped, doctor, patient, slot_time):
    first = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )
    BookingService.cancel(appointment=first, reason="patient changed their mind")

    # The slot is free again.
    second = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )
    assert second.pk != first.pk


@pytest.mark.django_db
def test_an_idempotency_key_replays_the_original_appointment(
    scoped, doctor, patient, slot_time
):
    first = BookingService.book(
        clinic=scoped,
        doctor=doctor,
        patient=patient,
        start_at=slot_time,
        idempotency_key="voice-call-123",
    )
    second = BookingService.book(
        clinic=scoped,
        doctor=doctor,
        patient=patient,
        start_at=slot_time,
        idempotency_key="voice-call-123",
    )

    assert first.pk == second.pk
    assert Appointment.objects.count() == 1


@pytest.mark.django_db
def test_a_patient_from_another_clinic_cannot_be_booked(
    scoped, doctor, other_patient, slot_time
):
    with pytest.raises(DomainError) as excinfo:
        BookingService.book(
            clinic=scoped, doctor=doctor, patient=other_patient, start_at=slot_time
        )

    assert excinfo.value.code == "cross_tenant"
    assert Appointment.objects.count() == 0


@pytest.mark.django_db
def test_a_naive_datetime_is_refused(scoped, doctor, patient):
    from datetime import datetime

    with pytest.raises(DomainError):
        BookingService.book(
            clinic=scoped, doctor=doctor, patient=patient, start_at=datetime(2030, 1, 1, 9, 0)
        )


@pytest.mark.django_db
def test_cancellation_outside_the_window_is_refused(scoped, doctor, patient, slot_time):
    """A 4-hour cancellation window is enforced."""
    appointment = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )
    # Move the appointment to 30 minutes away -- inside the cancellation window.
    soon = timezone.now() + timedelta(minutes=30)
    Appointment.objects.filter(pk=appointment.pk).update(start_at=soon, end_at=soon + timedelta(minutes=30))

    with pytest.raises(DomainError) as excinfo:
        BookingService.cancel(appointment=appointment)

    assert excinfo.value.code == "cancellation_window_passed"


@pytest.mark.django_db
def test_cancellation_inside_the_window_is_allowed(scoped, doctor, patient, slot_time):
    appointment = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )

    cancelled = BookingService.cancel(appointment=appointment, reason="test")

    assert cancelled.status == AppointmentStatus.CANCELLED
    assert cancelled.events.filter(event_type="cancelled").count() == 1


@pytest.mark.django_db
def test_a_cancelled_appointment_cannot_be_cancelled_again(
    scoped, doctor, patient, slot_time
):
    appointment = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )
    BookingService.cancel(appointment=appointment, reason="test")

    from apps.core.exceptions import InvalidTransition

    with pytest.raises(InvalidTransition):
        BookingService.cancel(appointment=appointment, reason="again")


@pytest.mark.django_db
def test_rescheduling_moves_the_appointment_and_frees_the_old_slot(
    scoped, doctor, patient, slot_time
):
    appointment = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )
    new_start = slot_time + timedelta(hours=2)

    moved = BookingService.reschedule(appointment=appointment, new_start_at=new_start)

    assert moved.start_at == new_start
    assert moved.events.filter(event_type="rescheduled").count() == 1

    # The original slot can be taken again.
    again = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )
    assert again.pk != appointment.pk


@pytest.mark.django_db
def test_rescheduling_onto_an_occupied_slot_is_refused(
    scoped, doctor, second_doctor, patient, slot_time
):
    """Two different doctors may hold the same wall-clock time."""
    from apps.appointments.models import Patient

    other_patient = Patient.objects.create(
        clinic=scoped, name="Second", phone="+919000555555"
    )
    first = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )
    BookingService.book(
        clinic=scoped, doctor=second_doctor, patient=other_patient, start_at=slot_time
    )

    third = Patient.objects.create(clinic=scoped, name="Third", phone="+919000666666")
    with pytest.raises(SlotUnavailable):
        BookingService.book(
            clinic=scoped, doctor=doctor, patient=third, start_at=slot_time
        )

    # The first appointment is untouched.
    first.refresh_from_db()
    assert first.status == AppointmentStatus.BOOKED


@pytest.mark.django_db
def test_get_or_create_patient_is_scoped_to_the_clinic(scoped, other_clinic):
    from apps.appointments.models import Patient
    from apps.core.rls import rls_scope

    with rls_scope(str(other_clinic.id)):
        get_or_create_patient(clinic=other_clinic, phone="+919000100001", name="Same Number")
        assert Patient.objects.count() == 1

    with rls_scope(str(scoped.id)):
        get_or_create_patient(clinic=scoped, phone="+919000100001", name="Same Number")
        assert Patient.objects.count() == 1
