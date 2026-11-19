"""Default weekly schedules for newly created doctors.

A doctor added from the dashboard has no ``DoctorSchedule`` rows, which makes
them unbookable — every date shows zero free slots. Give them the clinic's
configured operating hours on creation; staff can refine them afterwards via
the schedule endpoints.
"""
from __future__ import annotations

import logging
from datetime import time

from apps.doctors.models import Doctor, DoctorSchedule

logger = logging.getLogger("apps.doctors.schedule")

#: Matches the keys of ``ClinicSettings.operating_hours`` (Monday == 0).
_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _parse_time(value: object) -> time | None:
    try:
        return time.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def seed_default_schedule(doctor: Doctor) -> int:
    """Create recurring working windows from the clinic's opening hours.

    Returns the number of rows created. Existing schedules are left untouched,
    so this is safe to call for a doctor that was seeded with custom hours.
    """
    if DoctorSchedule.objects.filter(doctor=doctor).exists():
        return 0

    hours = doctor.clinic.config.operating_hours or {}
    created = 0
    for weekday, key in enumerate(_WEEKDAY_KEYS):
        rule = hours.get(key) or {}
        if rule.get("closed"):
            continue
        start = _parse_time(rule.get("open"))
        end = _parse_time(rule.get("close"))
        if start is None or end is None or start >= end:
            logger.warning(
                "skipping invalid operating hours for %s on %s: %r",
                doctor.slug,
                key,
                rule,
            )
            continue
        DoctorSchedule.objects.create(
            clinic=doctor.clinic,
            doctor=doctor,
            weekday=weekday,
            start_time=start,
            end_time=end,
        )
        created += 1
    return created
