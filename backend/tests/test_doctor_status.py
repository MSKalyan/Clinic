"""Doctor status (PRD 6).

The rules under test:

* ``present`` is an explicit human/integration assertion and is **never**
  inferred from the rota;
* a status that is older than the clinic's freshness threshold is reported
  as ``unknown`` and flagged stale;
* status events are append-only;
* changing a doctor's status never cancels their appointments.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.utils import timezone

from apps.core.constants import AppointmentStatus, DoctorStatus
from apps.doctors.models import DoctorStatusEvent
from apps.doctors.services.status import DoctorStatusService


#: A Monday at 10:00 IST, inside the seeded rota (09:00-13:00).
MONDAY_MORNING = datetime(2026, 11, 2, 4, 30, tzinfo=dt_timezone.utc)
#: The following Sunday at 10:00 IST -- no rota, no clinic opening hours.
SUNDAY_MORNING = datetime(2026, 11, 8, 4, 30, tzinfo=dt_timezone.utc)


@pytest.mark.django_db
def test_the_rota_never_yields_present(scoped, doctor):
    """A shift on the rota means ``scheduled`` -- never ``present``."""
    from freezegun import freeze_time

    with freeze_time(MONDAY_MORNING):
        snapshot = DoctorStatusService.get_current(doctor)

    assert snapshot.status == DoctorStatus.SCHEDULED
    assert snapshot.status != DoctorStatus.PRESENT
    assert not snapshot.is_present


@pytest.mark.django_db
def test_no_status_at_all_is_unknown_outside_the_rota(scoped, doctor):
    """With no explicit status and no shift, the doctor is ``unknown``."""
    from freezegun import freeze_time

    with freeze_time(SUNDAY_MORNING):
        snapshot = DoctorStatusService.get_current(doctor)

    assert snapshot.status == DoctorStatus.UNKNOWN
    assert snapshot.recorded_status == DoctorStatus.UNKNOWN
    assert not snapshot.is_present


@pytest.mark.django_db
def test_an_explicit_present_status_is_reported_as_present(scoped, doctor):
    DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.PRESENT, source="dashboard", notes="arrived"
    )

    snapshot = DoctorStatusService.get_current(doctor)

    assert snapshot.status == DoctorStatus.PRESENT
    assert snapshot.is_present
    assert not snapshot.is_stale
    assert snapshot.source == "dashboard"


@pytest.mark.django_db
def test_a_stale_status_degrades_to_unknown(scoped, doctor):
    """``present`` goes stale after 60 minutes by default."""
    from freezegun import freeze_time

    DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.PRESENT, source="dashboard"
    )

    with freeze_time(timezone.now() + timedelta(minutes=59)):
        assert DoctorStatusService.get_current(doctor).status == DoctorStatus.PRESENT

    with freeze_time(timezone.now() + timedelta(minutes=61)):
        snapshot = DoctorStatusService.get_current(doctor)
        assert snapshot.status == DoctorStatus.UNKNOWN
        assert snapshot.is_stale
        # The *recorded* status is still visible for the dashboard.
        assert snapshot.recorded_status == DoctorStatus.PRESENT


@pytest.mark.django_db
def test_the_freshness_threshold_is_per_clinic(scoped, doctor):
    """A clinic can tighten or loosen the threshold for itself."""
    from apps.tenancy.models import ClinicSettings

    DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.RUNNING_LATE, source="dashboard"
    )

    # The default threshold for ``running_late`` is 30 minutes.
    assert DoctorStatusService.is_stale(
        scoped, DoctorStatus.RUNNING_LATE, timezone.now() - timedelta(minutes=20)
    ) is False

    settings_row = ClinicSettings.objects.get(clinic=scoped)
    settings_row.status_freshness_minutes = {"running_late": 10}
    settings_row.save(update_fields=["status_freshness_minutes", "updated_at"])

    assert DoctorStatusService.is_stale(
        scoped, DoctorStatus.RUNNING_LATE, timezone.now() - timedelta(minutes=20)
    ) is True


@pytest.mark.django_db
def test_an_expired_status_is_treated_as_stale(scoped, doctor):
    DoctorStatusService.record(
        doctor=doctor,
        status=DoctorStatus.PRESENT,
        source="dashboard",
        effective_until=timezone.now() - timedelta(minutes=1),
    )

    snapshot = DoctorStatusService.get_current(doctor)

    assert snapshot.status == DoctorStatus.UNKNOWN
    assert snapshot.is_stale


@pytest.mark.django_db
def test_status_events_are_append_only(scoped, doctor):
    DoctorStatusService.record(doctor=doctor, status=DoctorStatus.PRESENT, source="dashboard")
    DoctorStatusService.record(doctor=doctor, status=DoctorStatus.ON_LEAVE, source="dashboard")

    events = DoctorStatusEvent.objects.filter(doctor=doctor).order_by("sequence")
    assert events.count() == 2
    assert [e.status for e in events] == [DoctorStatus.PRESENT, DoctorStatus.ON_LEAVE]
    # The sequence number increases, so the history is ordered.
    assert events[1].sequence > events[0].sequence


@pytest.mark.django_db
def test_the_current_pointer_is_versioned(scoped, doctor):
    first = DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.PRESENT, source="dashboard"
    )
    second = DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.RUNNING_LATE, source="voice"
    )

    assert first.version == 1
    assert second.version == 2


@pytest.mark.django_db
def test_changing_a_status_does_not_cancel_appointments(
    scoped, doctor, patient, slot_time
):
    """PRD 6.5: a status change must not silently cancel appointments."""
    from apps.appointments.models import Appointment
    from apps.appointments.services.booking import BookingService

    appointment = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )

    DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.FINISHED_FOR_DAY, source="dashboard"
    )

    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.BOOKED
    assert Appointment.objects.filter(status=AppointmentStatus.CANCELLED).count() == 0


@pytest.mark.django_db
def test_a_blocking_status_stops_new_bookings(scoped, doctor, patient, slot_time):
    from apps.appointments.services.booking import BookingService
    from apps.core.exceptions import SlotUnavailable

    DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.UNAVAILABLE, source="dashboard"
    )

    with pytest.raises(SlotUnavailable):
        BookingService.book(clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time)


@pytest.mark.django_db
def test_a_status_change_emits_an_outbox_event(scoped, doctor):
    from apps.core.constants import InternalEventType
    from apps.core.models import OutboxEvent

    DoctorStatusService.record(
        doctor=doctor, status=DoctorStatus.PRESENT, source="dashboard"
    )

    event = OutboxEvent.objects.filter(
        event_type=InternalEventType.DOCTOR_STATUS_CHANGED
    ).first()
    assert event is not None
    assert event.payload["status"] == DoctorStatus.PRESENT
    assert event.payload["source"] == "dashboard"
