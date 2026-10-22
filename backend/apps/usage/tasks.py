"""Usage aggregation tasks."""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("apps.usage.tasks")


@shared_task(name="apps.usage.tasks.aggregate_daily_usage")
def aggregate_daily_usage() -> dict[str, int]:
    """Roll up yesterday's usage per clinic.

    The raw ``usage_events`` rows remain the source of truth; this produces
    the figures the dashboard and the invoice run read.
    """
    from django.db.models import Sum

    from apps.core.rls import iter_clinic_scopes
    from apps.usage.models import UsageEvent

    yesterday = timezone.now() - timedelta(days=1)
    clinics = 0
    for clinic, _scope in iter_clinic_scopes():
        row = (
            UsageEvent.objects.filter(clinic=clinic, recorded_at__gte=yesterday)
            .values("clinic_id")
            .annotate(total=Sum("quantity"))
            .first()
        )
        if row is None:
            continue
        clinics += 1
        logger.debug("clinic %s used %s yesterday", row["clinic_id"], row["total"])
    return {"clinics": clinics}
