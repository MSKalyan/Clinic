"""The availability engine (PRD 5.1).

The engine is the single source of truth for "can this patient book this
time?". It must never *guess*: a slot exists only if the rota says the
doctor is working, the clinic is open, no exception closes the window, the
doctor is not on leave and nothing else is already booked.
"""
from __future__ import annotations

from datetime import time, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.utils import timezone

from apps.appointments.services.availability import AvailabilityService
from apps.core.constants import DoctorStatus
from apps.core.timeutils import combine_local, get_zone, to_clinic_local


@pytest.mark.django_db
def test_slots_follow_the_rota(scoped, doctor, next_monday):
    """Monday 09:00-13:00 and 16:00-19:00 -> 14 thirty-minute slots."""
    availability = AvailabilityService(scoped)

    slots = availability.slots(doctors=[doctor], on_date=next_monday)

    assert len(slots) == 14
    assert slots[0].display_start == "09:00"
    assert slots[0].display_end == "09:30"
    assert slots[-1].display_start == "18:30"
    assert slots[-1].display_end == "19:00"
    # Two windows, so the afternoon block starts at 16:00.
    assert [s.display_start for s in slots if s.display_start.startswith("16")][0] == "16:00"


@pytest.mark.django_db
def test_no_slots_on_a_closed_day(scoped, doctor):
    """The clinic is closed on Sundays, so there are no Sunday slots."""
    sunday = timezone.localdate()
    while sunday.weekday() != 6:
        sunday += timedelta(days=1)

    slots = AvailabilityService(scoped).slots(doctors=[doctor], on_date=sunday)

    assert slots == []


@pytest.mark.django_db
def test_clinic_opening_hours_clip_the_rota(scoped, doctor, next_monday):
    """A doctor who works past closing time only offers in-hours slots."""
    from apps.doctors.models import DoctorSchedule

    DoctorSchedule.objects.filter(clinic=scoped, doctor=doctor, weekday=next_monday.weekday()).delete()
    DoctorSchedule.objects.create(
        clinic=scoped,
        doctor=doctor,
        weekday=next_monday.weekday(),
        start_time=time(9, 0),
        end_time=time(23, 0),
    )

    slots = AvailabilityService(scoped).slots(doctors=[doctor], on_date=next_monday)

    # The clinic closes at 19:00, so the last slot ends then -- never later.
    assert slots
    assert all(s.display_end <= "19:00" for s in slots)
    assert slots[-1].display_end == "19:00"


@pytest.mark.django_db
def test_slots_are_stored_in_utc_and_displayed_locally(scoped, doctor, next_monday):
    """Timestamps are UTC; the display strings are in the clinic's zone."""
    from apps.appointments.models import Appointment
    from apps.appointments.services.booking import BookingService
    from apps.core.timeutils import combine_local, get_zone, to_clinic_local

    slots = AvailabilityService(scoped).slots(doctors=[doctor], on_date=next_monday)

    first = slots[0]
    assert first.start_at.tzinfo is not None
    # The instant is 09:00 in the clinic's own timezone ...
    assert first.start_at == combine_local(next_monday, time(9, 0), get_zone("Asia/Kolkata"))
    # ... which is 03:30 UTC.
    assert first.start_at.astimezone(dt_timezone.utc).strftime("%H:%M") == "03:30"
    assert first.display_start == to_clinic_local(first.start_at, scoped).strftime("%H:%M")

    # And it is *stored* in UTC: a fresh read comes back on the UTC offset.
    BookingService.book(clinic=scoped, doctor=doctor, patient=_patient(scoped), start_at=first.start_at)
    stored = Appointment.objects.get(doctor=doctor)
    assert stored.start_at.utcoffset() == timedelta(0)
    assert stored.start_at == first.start_at


def _patient(clinic):
    from apps.appointments.models import Patient

    return Patient.objects.create(clinic=clinic, name="Slot Test", phone="+919000123456")


@pytest.mark.django_db
def test_booking_horizon_is_enforced(scoped, doctor):
    """Nothing is offered beyond the 30-day horizon."""
    availability = AvailabilityService(scoped)

    slots = availability.slots(doctors=[doctor])

    horizon = timezone.now() + timedelta(days=30)
    assert slots
    assert all(s.start_at <= horizon for s in slots)


@pytest.mark.django_db
def test_an_unavailable_exception_closes_the_window(scoped, doctor, next_monday):
    from apps.doctors.models import DoctorScheduleException

    DoctorScheduleException.objects.create(
        clinic=scoped,
        doctor=doctor,
        date=next_monday,
        start_time=time(9, 0),
        end_time=time(11, 0),
        kind="unavailable",
    )

    slots = AvailabilityService(scoped).slots(doctors=[doctor], on_date=next_monday)

    assert all(not (s.display_start < "11:00" and s.display_end > "09:00") for s in slots)
    # The afternoon block is untouched.
    assert any(s.display_start == "16:00" for s in slots)


@pytest.mark.django_db
def test_an_available_exception_opens_an_extra_window(scoped, doctor, next_monday):
    from apps.doctors.models import DoctorScheduleException

    DoctorScheduleException.objects.create(
        clinic=scoped,
        doctor=doctor,
        date=next_monday,
        start_time=time(14, 0),
        end_time=time(15, 0),
        kind="available",
    )

    slots = AvailabilityService(scoped).slots(doctors=[doctor], on_date=next_monday)

    assert any(s.display_start == "14:00" for s in slots)
    assert any(s.display_start == "14:30" for s in slots)


@pytest.mark.django_db
def test_a_booked_slot_disappears(scoped, doctor, patient, slot_time):
    from apps.appointments.services.booking import BookingService

    BookingService.book(clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time)

    slots = AvailabilityService(scoped).slots(doctors=[doctor])

    assert all(s.start_at != slot_time for s in slots)


@pytest.mark.django_db
def test_the_buffer_prevents_a_slot_straight_after_an_appointment(
    scoped, doctor, patient, slot_time
):
    """Ten minutes of turnaround time means 09:00-09:10 is not bookable."""
    from apps.appointments.services.booking import BookingService

    BookingService.book(clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time)

    slots = AvailabilityService(scoped).slots(doctors=[doctor])

    assert all(s.start_at != slot_time + timedelta(minutes=30) for s in slots)


@pytest.mark.django_db
def test_a_doctor_on_leave_offers_no_slots(scoped, doctor, next_monday):
    from apps.doctors.services.status import DoctorStatusService

    DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.ON_LEAVE, source="dashboard"
    )

    availability = AvailabilityService(scoped)

    assert availability.slots(doctors=[doctor], on_date=next_monday) == []
    assert not availability.is_slot_available(doctor, combine_local(next_monday, time(9, 0), get_zone("Asia/Kolkata")))


@pytest.mark.django_db
def test_unavailable_slots_are_reported_when_requested(scoped, doctor, next_monday):
    """``include_unavailable`` keeps the slot but explains why it is closed."""
    from apps.doctors.services.status import DoctorStatusService

    DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.ON_LEAVE, source="dashboard"
    )

    slots = AvailabilityService(scoped).slots(
        doctors=[doctor], on_date=next_monday, include_unavailable=True
    )

    assert slots
    assert all(not s.available for s in slots)
    assert all("on leave" in s.reason for s in slots)


@pytest.mark.django_db
def test_is_slot_available_rejects_a_time_outside_the_rota(scoped, doctor, next_monday):
    availability = AvailabilityService(scoped)

    # 13:15 is inside the clinic's opening hours but not the doctor's rota.
    assert not availability.is_slot_available(
        doctor, combine_local(next_monday, time(13, 15), get_zone("Asia/Kolkata"))
    )
    assert availability.is_slot_available(
        doctor, combine_local(next_monday, time(9, 0), get_zone("Asia/Kolkata"))
    )
