"""Appointment reminders and notification scheduling.

The Celery task here is the *sweep*. The rules it enforces live in
``apps.appointments.services.reminders`` so that the booking service can
use them without depending on the task module.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.appointments.models import ReminderLog
from apps.appointments.services.reminders import (
    TERMINAL_APPOINTMENT_STATUSES,
    reminder_matches_appointment,
)
from apps.core.constants import ConsentPurpose

logger = logging.getLogger("apps.appointments.reminders")


@shared_task(name="apps.appointments.tasks.scan_appointment_reminders")
def scan_appointment_reminders(limit: int = 200) -> dict[str, int]:
    """Send the reminders that are due.

    Every reminder is tracked to a terminal state: a reminder whose
    appointment was cancelled or rescheduled is marked ``cancelled`` rather
    than silently dropped (PRD 4.5).

    The sweep runs one tenant at a time so that a reminder can never be
    sent with another clinic's configuration or provider connection.
    """
    from apps.conversations.services.notifications import NotificationService
    from apps.core.exceptions import ConsentRequired, OptedOut
    from apps.core.rls import iter_clinic_scopes

    now = timezone.now()
    sent = 0
    skipped = 0
    failed = 0

    for clinic, _scope in iter_clinic_scopes():
        due = ReminderLog.objects.filter(
            clinic=clinic, status="pending", due_at__lte=now
        ).order_by("due_at")[:limit]

        for reminder in due:
            appointment = reminder.appointment

            # The reminder must reflect the *latest* appointment state.
            if appointment.status in TERMINAL_APPOINTMENT_STATUSES:
                reminder.status = "cancelled"
                reminder.save(update_fields=["status"])
                skipped += 1
                continue

            if not reminder_matches_appointment(reminder):
                # The appointment moved: this reminder talks about a time
                # that is no longer true.
                reminder.status = "cancelled"
                reminder.save(update_fields=["status"])
                skipped += 1
                continue

            try:
                NotificationService.send(
                    clinic=reminder.clinic,
                    patient=appointment.patient,
                    channel=reminder.channel,
                    template_id=reminder.template_id,
                    body=(
                        f"Reminder: your appointment with {appointment.doctor.name} "
                        f"is on {appointment.start_at.isoformat()}."
                    ),
                    appointment=appointment,
                    purpose=ConsentPurpose.REMINDERS,
                    idempotency_key=reminder.idempotency_key,
                    payload={"reference": appointment.reference},
                )
            except (ConsentRequired, OptedOut) as exc:
                reminder.status = "skipped"
                reminder.last_error = str(exc)[:500]
                reminder.save(update_fields=["status", "last_error"])
                skipped += 1
                continue
            except Exception as exc:  # pragma: no cover - provider dependent
                reminder.attempts += 1
                reminder.last_error = str(exc)[:2000]
                if reminder.attempts >= 3:
                    reminder.status = "failed"
                reminder.save(update_fields=["attempts", "last_error", "status"])
                failed += 1
                continue

            reminder.status = "sent"
            reminder.sent_at = timezone.now()
            reminder.attempts += 1
            reminder.save(update_fields=["status", "sent_at", "attempts"])
            sent += 1

    return {"sent": sent, "skipped": skipped, "failed": failed}
