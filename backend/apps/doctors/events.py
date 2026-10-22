"""Handlers for doctor availability events.

When a doctor becomes unavailable -- or simply runs late -- the patients
who are booked with them need a human to act. The assistant may not
re-book or cancel anything on its own, so the outcome is always a
follow-up task for the clinic team (PRD 5.3 / 6.4).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from apps.core.constants import (
    BLOCKING_STATUSES,
    DoctorStatus,
    FollowUpTaskType,
    InternalEventType,
    TaskPriority,
)
from apps.core.events import register

logger = logging.getLogger("apps.doctors.events")

#: How far ahead a status change affects booked patients.
LOOKAHEAD_HOURS = 24


@register(InternalEventType.DOCTOR_STATUS_CHANGED)
def on_doctor_status_changed(event) -> None:
    """Turn a status change into follow-up work when it affects patients."""
    payload = event.payload or {}
    status = str(payload.get("status") or "")
    if not status:
        return

    if status in {s.value for s in BLOCKING_STATUSES}:
        task_type = FollowUpTaskType.LEAVE_RESCHEDULE
        priority = TaskPriority.HIGH
    elif status == DoctorStatus.RUNNING_LATE.value:
        task_type = FollowUpTaskType.DELAY_NOTIFICATION
        priority = TaskPriority.NORMAL
    else:
        return

    doctor_id = payload.get("doctor_id")
    if not doctor_id:
        return

    from apps.appointments.models import Appointment
    from apps.conversations.services.followups import FollowUpService
    from apps.doctors.models import Doctor

    doctor = Doctor.objects.filter(pk=doctor_id).first()
    if doctor is None:
        return

    now = timezone.now()
    affected = (
        Appointment.objects.filter(
            clinic=doctor.clinic,
            doctor=doctor,
            status__in=["booked", "confirmed"],
            start_at__gte=now,
            start_at__lte=now + timedelta(hours=LOOKAHEAD_HOURS),
        )
        .select_related("patient")
        .order_by("start_at")
    )

    for appointment in affected:
        dedupe = FollowUpService.dedupe_key(
            "doctor_status", doctor.id, status, appointment.id
        )
        FollowUpService.create_task(
            clinic=doctor.clinic,
            task_type=task_type,
            dedupe_key=dedupe,
            patient=appointment.patient,
            related_appointment=appointment,
            priority=priority,
            due_in_minutes=60,
            notes=(
                f"{doctor.name} is {status.replace('_', ' ')}. "
                f"The appointment at {appointment.start_at.isoformat()} may be affected."
            ),
        )

    logger.info(
        "doctor status %s for %s produced %s follow-up task(s)",
        status,
        doctor.id,
        len(affected),
    )
