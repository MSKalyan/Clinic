"""Reminder scheduling.

Reminders are derived from an appointment, so they have to follow it. Two
rules make that safe:

* a reminder is created at most once per (appointment, channel, offset,
  appointment start) -- the idempotency key carries the start time, so a
  *rescheduled* appointment gets a fresh set of reminders while the old
  ones are cancelled rather than silently dropped;
* a reminder that no longer matches its appointment reaches a terminal
  state (``cancelled``), so the clinic can tell "sent" apart from
  "never applicable" (PRD 4.5).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.appointments.models import Appointment, ReminderLog
from apps.core.constants import AppointmentStatus, InternalEventType
from apps.core.models import OutboxEvent

logger = logging.getLogger("apps.appointments.reminders")

#: Appointment statuses after which a reminder no longer makes sense.
TERMINAL_APPOINTMENT_STATUSES = {
    AppointmentStatus.CANCELLED,
    AppointmentStatus.COMPLETED,
    AppointmentStatus.NO_SHOW,
}


def reminder_idempotency_key(
    appointment: Appointment, channel: str, offset_hours: int
) -> str:
    """A stable key so a reminder is only ever sent once.

    The appointment's start time is part of the key on purpose: if the
    appointment moves, the reminder for the old time must not be
    re-sent, and the reminder for the new time must be a *different*
    reminder.
    """
    return (
        f"reminder:{appointment.id}:{channel}:{int(offset_hours)}:"
        f"{appointment.start_at.isoformat()}"
    )


def reminder_expected_start(reminder: ReminderLog) -> datetime:
    """The appointment start a reminder was scheduled for.

    Read from the stored column. Falling back to ``due_at + offset``
    keeps rows created before the column existed usable.
    """
    stored = getattr(reminder, "scheduled_start_at", None)
    if stored is not None:
        return stored
    return reminder.due_at + timedelta(hours=int(reminder.offset_hours))


def reminder_matches_appointment(reminder: ReminderLog) -> bool:
    """Is this reminder still the one the appointment needs?

    A rescheduled appointment changes ``start_at`` but leaves the queued
    reminder pointing at the old time. Comparing against the time the
    reminder was *scheduled* for is what detects the move.
    """
    return reminder.appointment.start_at == reminder_expected_start(reminder)


def schedule_reminders(appointment: Appointment, *, now=None) -> list[ReminderLog]:
    """Create the reminder rows for an appointment.

    Creating the rows is idempotent: the unique key means a re-run does
    not create a second reminder, and an appointment that has since been
    cancelled or rescheduled is skipped entirely.
    """
    now = now or timezone.now()
    clinic = appointment.clinic
    policy = clinic.reminder_policy()
    created: list[ReminderLog] = []

    for offset_hours in policy.get("offsets_hours", []):
        due_at = appointment.start_at - timedelta(hours=int(offset_hours))
        if due_at <= now:
            continue
        for channel in policy.get("channels", []):
            key = reminder_idempotency_key(appointment, channel, int(offset_hours))
            try:
                # The savepoint keeps a duplicate from poisoning an
                # enclosing transaction -- only this insert is rolled back.
                with transaction.atomic():
                    reminder = ReminderLog.objects.create(
                        clinic=clinic,
                        appointment=appointment,
                        channel=channel,
                        template_id="appointment_reminder",
                        offset_hours=int(offset_hours),
                        due_at=due_at,
                        scheduled_start_at=appointment.start_at,
                        idempotency_key=key,
                        status="pending",
                    )
            except IntegrityError:
                continue
            created.append(reminder)
            OutboxEvent.objects.create(
                clinic=clinic,
                event_type=InternalEventType.REMINDER_DUE,
                payload={
                    "reminder_id": str(reminder.id),
                    "appointment_id": str(appointment.id),
                    "due_at": due_at.isoformat(),
                    "channel": channel,
                },
            )
    return created


def cancel_stale_reminders(appointment: Appointment) -> int:
    """Cancel the reminders that no longer apply to the appointment.

    A reminder stops applying when the appointment moves (the message talks
    about a time that is no longer true) or when the appointment reaches a
    terminal status (there is nothing left to remind about).

    Returns the number of reminders that were cancelled. The rows are
    kept, with a terminal status, so the clinic can audit what happened.
    """
    cancelled = 0
    pending = ReminderLog.objects.filter(
        clinic=appointment.clinic, appointment=appointment, status="pending"
    )
    for reminder in pending:
        if appointment.status in TERMINAL_APPOINTMENT_STATUSES:
            pass
        elif reminder_matches_appointment(reminder):
            continue
        reminder.status = "cancelled"
        reminder.save(update_fields=["status"])
        cancelled += 1
    if cancelled:
        logger.info(
            "cancelled %s stale reminder(s) for appointment %s",
            cancelled,
            appointment.id,
        )
    return cancelled
