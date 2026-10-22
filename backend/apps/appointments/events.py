"""Handlers for the appointment lifecycle events.

These run when the outbox publisher drains the queue, so the work they do
(scheduling reminders, cleaning up reminders for an appointment that moved
or was cancelled) never sits in the request path and never blocks a
booking (PRD 11.3).
"""
from __future__ import annotations

import logging

from apps.core.constants import InternalEventType
from apps.core.events import register

logger = logging.getLogger("apps.appointments.events")


def _appointment(event):
    """The appointment an event refers to, if it still exists."""
    from apps.appointments.models import Appointment

    appointment_id = (event.payload or {}).get("appointment_id")
    if not appointment_id:
        return None
    return Appointment.objects.filter(pk=appointment_id).first()


@register(InternalEventType.APPOINTMENT_BOOKED)
def on_appointment_booked(event) -> None:
    """A booking needs its reminder plan."""
    from apps.appointments.services.reminders import schedule_reminders

    appointment = _appointment(event)
    if appointment is None:
        logger.warning("booked event %s refers to an unknown appointment", event.pk)
        return
    created = schedule_reminders(appointment)
    logger.info(
        "scheduled %s reminder(s) for appointment %s", len(created), appointment.id
    )


@register(InternalEventType.APPOINTMENT_RESCHEDULED)
def on_appointment_rescheduled(event) -> None:
    """The reminders for the old time are cancelled, new ones are queued."""
    from apps.appointments.services.reminders import (
        cancel_stale_reminders,
        schedule_reminders,
    )

    appointment = _appointment(event)
    if appointment is None:
        return
    cancel_stale_reminders(appointment)
    schedule_reminders(appointment)


@register(InternalEventType.APPOINTMENT_CANCELLED)
def on_appointment_cancelled(event) -> None:
    """A cancelled appointment must not be reminded about."""
    from apps.appointments.services.reminders import cancel_stale_reminders

    appointment = _appointment(event)
    if appointment is None:
        return
    cancel_stale_reminders(appointment)


@register(InternalEventType.REMINDER_DUE)
def on_reminder_due(event) -> None:
    """The reminder was queued.

    Delivery is time-based, so the sweep (``scan_appointment_reminders``)
    owns it: this handler exists so the event is not an unhandled one.
    """
    logger.debug("reminder queued: %s", (event.payload or {}).get("reminder_id"))
