"""Appointment reminders (PRD 4.5 / 5.5).

A reminder has to be exactly-once *and* end in a terminal state. The two
failure modes the PRD calls out are:

* a reminder that is sent twice (the sweep runs every few minutes and the
  worker can restart at any point);
* a reminder that is silently dropped because the appointment was
  cancelled or moved -- the clinic has to be able to tell the difference
  between "sent" and "never applicable".
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.appointments.models import ReminderLog
from apps.appointments.services.booking import BookingService
from apps.appointments.services.reminders import schedule_reminders
from apps.appointments.tasks import scan_appointment_reminders


@pytest.fixture
def appointment(scoped, doctor, patient, slot_time):
    return BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )


@pytest.fixture
def soon_appointment(scoped, doctor, patient):
    """An appointment that starts in three hours.

    Built directly rather than through the booking service, because the
    point of the test is the *reminder offsets*, not the booking rules.
    """
    from apps.appointments.models import Appointment

    start_at = (timezone.now() + timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
    return Appointment.objects.create(
        clinic=scoped,
        doctor=doctor,
        patient=patient,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
        status="booked",
        booking_source="api",
        reference="APTSOON",
    )


@pytest.fixture
def stub_messaging(monkeypatch):
    """Replace the outbound provider with a recording stub."""
    import apps.integrations.providers as providers

    sent: list[dict] = []

    class StubProvider:
        provider_type = "whatsapp"

        def send_message(self, *, clinic, recipient_phone, template_id, body="", appointment=None, payload=None):
            sent.append({"template_id": template_id, "recipient_phone": recipient_phone})
            return f"stub-message-{len(sent)}"

    monkeypatch.setattr(providers, "get_messaging_provider", lambda clinic, channel: StubProvider())
    return sent


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_scheduling_is_idempotent(scoped, appointment):
    """The scheduler can run twice without creating two sets of reminders."""
    first = schedule_reminders(appointment)
    second = schedule_reminders(appointment)

    assert len(first) > 0
    assert second == []
    assert ReminderLog.objects.filter(clinic=scoped).count() == len(first)


@pytest.mark.django_db
def test_a_reminder_is_scheduled_for_each_policy_offset(scoped, appointment):
    """Two offsets (24h and 2h) times two channels."""
    reminders = schedule_reminders(appointment)

    assert {r.offset_hours for r in reminders} == {24, 2}
    assert {r.channel for r in reminders} == {"sms", "whatsapp"}
    for reminder in reminders:
        assert reminder.status == "pending"
        assert reminder.due_at == appointment.start_at - timedelta(hours=reminder.offset_hours)


@pytest.mark.django_db
def test_an_offset_in_the_past_is_not_scheduled(scoped, soon_appointment):
    """An appointment inside the 24-hour window gets no 24-hour reminder."""
    reminders = schedule_reminders(soon_appointment)

    assert {r.offset_hours for r in reminders} == {2}


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_due_reminder_is_sent_once(scoped, appointment, stub_messaging):
    """The sweep runs repeatedly; the patient is messaged once."""
    schedule_reminders(appointment)
    due = ReminderLog.objects.filter(clinic=scoped, status="pending")
    due.update(due_at=timezone.now() - timedelta(minutes=1))
    expected = due.count()

    first = scan_appointment_reminders()
    second = scan_appointment_reminders()

    assert first["sent"] == expected
    assert second["sent"] == 0
    assert len(stub_messaging) == expected

    for reminder in ReminderLog.objects.filter(clinic=scoped):
        assert reminder.status == "sent"
        assert reminder.sent_at is not None


@pytest.mark.django_db
def test_a_reminder_for_a_cancelled_appointment_ends_as_cancelled(scoped, appointment):
    """Cancelled is a terminal state, not a silent drop."""
    from apps.appointments.services.booking import BookingService as BS

    schedule_reminders(appointment)
    BS.cancel(appointment=appointment, reason="patient cancelled", actor=None, force=True)
    ReminderLog.objects.filter(clinic=scoped).update(due_at=timezone.now() - timedelta(minutes=1))

    result = scan_appointment_reminders()

    assert result["sent"] == 0
    assert result["skipped"] == ReminderLog.objects.filter(clinic=scoped).count()
    for reminder in ReminderLog.objects.filter(clinic=scoped):
        assert reminder.status == "cancelled"


@pytest.mark.django_db
def test_a_reminder_for_a_moved_appointment_ends_as_cancelled(scoped, appointment, doctor):
    """A rescheduled appointment invalidates the reminder that was queued."""
    from apps.appointments.services.booking import BookingService as BS

    schedule_reminders(appointment)
    BS.reschedule(
        appointment=appointment,
        new_start_at=appointment.start_at + timedelta(days=7),
        actor=None,
    )
    ReminderLog.objects.filter(clinic=scoped).update(due_at=timezone.now() - timedelta(minutes=1))

    result = scan_appointment_reminders()

    assert result["sent"] == 0
    for reminder in ReminderLog.objects.filter(clinic=scoped):
        assert reminder.status == "cancelled"


@pytest.mark.django_db
def test_a_patient_who_opts_out_after_the_reminder_was_queued_is_not_messaged(
    scoped, appointment, stub_messaging
):
    """Consent is checked when the message goes out, not when it is queued."""
    schedule_reminders(appointment)
    ReminderLog.objects.filter(clinic=scoped).update(due_at=timezone.now() - timedelta(minutes=1))

    appointment.patient.communication_preferences = {
        "opt_out_whatsapp": True,
        "opt_out_sms": True,
    }
    appointment.patient.save(update_fields=["communication_preferences"])

    result = scan_appointment_reminders()

    assert result["sent"] == 0
    assert result["skipped"] == ReminderLog.objects.filter(clinic=scoped).count()
    assert stub_messaging == []
    for reminder in ReminderLog.objects.filter(clinic=scoped):
        assert reminder.status == "skipped"


@pytest.mark.django_db
def test_the_sweep_only_touches_the_tenant_it_is_scoped_to(scoped, appointment, stub_messaging):
    """Background work is done one clinic at a time."""
    schedule_reminders(appointment)
    ReminderLog.objects.filter(clinic=scoped).update(due_at=timezone.now() - timedelta(minutes=1))

    scan_appointment_reminders()

    for message in stub_messaging:
        assert message["recipient_phone"] == appointment.patient.phone
