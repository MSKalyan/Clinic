"""Timezone helpers.

All timestamps are stored in UTC. Display and *business logic* (does this
slot fall inside the clinic's operating hours?) always happens in the
clinic's configured timezone.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

DEFAULT_TIMEZONE = "UTC"


def get_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def clinic_zone(clinic) -> ZoneInfo:  # noqa: ANN001
    return get_zone(getattr(clinic, "timezone", None))


def to_clinic_local(value: datetime, clinic) -> datetime:  # noqa: ANN001
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.utc)
    return value.astimezone(clinic_zone(clinic))


def local_date(value: datetime, clinic) -> date:  # noqa: ANN001
    return to_clinic_local(value, clinic).date()


def combine_local(day: date, moment: time, zone: ZoneInfo) -> datetime:
    """Build an aware datetime from a local date + time in ``zone``."""
    return datetime.combine(day, moment).replace(tzinfo=zone)


def start_of_local_day(day: date, zone: ZoneInfo) -> datetime:
    return combine_local(day, time(0, 0), zone)


def end_of_local_day(day: date, zone: ZoneInfo) -> datetime:
    return combine_local(day, time(23, 59, 59), zone)


def minutes_since_midnight(moment: time) -> int:
    return moment.hour * 60 + moment.minute


def add_days(day: date, days: int) -> date:
    return day + timedelta(days=days)


def now() -> datetime:
    return timezone.now()
