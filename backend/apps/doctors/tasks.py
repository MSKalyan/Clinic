"""Background tasks for doctor availability."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.core.constants import DoctorStatus
from apps.doctors.models import DoctorStatusCurrent

logger = logging.getLogger("apps.doctors.tasks")


@shared_task(name="apps.doctors.tasks.scan_stale_doctor_status")
def scan_stale_doctor_status(limit: int = 500) -> dict[str, int]:
    """Degrade stale statuses to ``unknown``.

    PRD 6.3.5: "Expired or stale updates revert to an appropriate unknown
    state rather than remaining indefinitely valid." The original event stays
    in the history -- we only add a new event.

    The sweep runs one tenant at a time so that the database session is
    always scoped to the clinic the doctor belongs to.
    """
    from apps.core.rls import iter_clinic_scopes
    from apps.doctors.services.status import DoctorStatusService

    reverted = 0
    now = timezone.now()

    for clinic, _scope in iter_clinic_scopes():
        currents = (
            DoctorStatusCurrent.objects.select_related("clinic", "doctor")
            .filter(clinic=clinic)
            .exclude(current_status=DoctorStatus.UNKNOWN)
            .exclude(
                current_status__in=[DoctorStatus.ON_LEAVE, DoctorStatus.FINISHED_FOR_DAY]
            )
            .order_by("clinic_id")[:limit]
        )

        for current in currents:
            if not DoctorStatusService.is_stale(
                current.clinic, current.current_status, current.last_confirmed_at
            ):
                continue
            if current.current_event is not None and current.current_event.effective_until:
                if current.current_event.effective_until > now:
                    continue
            try:
                DoctorStatusService.record(
                    doctor=current.doctor,
                    status=DoctorStatus.UNKNOWN,
                    source="scheduler",
                    notes="Automatically reverted: recorded status became stale.",
                )
                reverted += 1
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "failed to revert stale status for doctor %s", current.doctor_id
                )

    return {"reverted": reverted}
