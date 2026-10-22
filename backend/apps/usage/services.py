"""Usage metering.

Usage is recorded per tenant with an idempotency key, so a retried provider
webhook cannot inflate a clinic's bill (PRD 15.3).
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger("apps.usage.meter")


class UsageMeter:
    """Record metered usage."""

    @staticmethod
    def record(
        *,
        clinic,
        event_type: str,
        quantity: float | Decimal,
        unit: str,
        idempotency_key: str,
        provider_cost: float | Decimal = 0,
        provider_connection=None,
        provider_reference: str = "",
        recorded_at: datetime | None = None,
        metadata: dict | None = None,
    ):
        from apps.usage.models import UsageEvent

        try:
            # A savepoint keeps a duplicate from poisoning an enclosing
            # transaction: only this insert is rolled back.
            with transaction.atomic():
                return UsageEvent.objects.create(
                    clinic=clinic,
                    provider_connection=provider_connection,
                    event_type=event_type,
                    quantity=Decimal(str(quantity)),
                    unit=unit,
                    provider_cost=Decimal(str(provider_cost)),
                    provider_reference=provider_reference,
                    recorded_at=recorded_at or timezone.now(),
                    idempotency_key=idempotency_key,
                    metadata=metadata or {},
                )
        except IntegrityError:
            existing = UsageEvent.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing
            raise

    @staticmethod
    def summarise(clinic, *, since: datetime | None = None) -> dict:  # noqa: ANN001
        """Aggregate usage for a clinic, grouped by event type."""
        from decimal import Decimal

        from django.db.models import DecimalField, Sum, Value
        from django.db.models.functions import Coalesce

        from apps.usage.models import UsageEvent

        queryset = UsageEvent.objects.filter(clinic=clinic)
        if since:
            queryset = queryset.filter(recorded_at__gte=since)

        # ``quantity`` and ``provider_cost`` are decimals, so the zero we
        # coalesce to has to be a decimal too -- otherwise Django cannot
        # resolve the output type of the expression.
        zero = Value(Decimal("0"), output_field=DecimalField(max_digits=12, decimal_places=4))

        rows = queryset.values("event_type", "unit").annotate(
            total=Coalesce(Sum("quantity"), zero, output_field=DecimalField(max_digits=12, decimal_places=4)),
            cost=Coalesce(Sum("provider_cost"), zero, output_field=DecimalField(max_digits=12, decimal_places=4)),
        )
        return {
            "by_event_type": [
                {
                    "event_type": row["event_type"],
                    "unit": row["unit"],
                    "quantity": float(row["total"]),
                    "provider_cost": float(row["cost"]),
                }
                for row in rows
            ]
        }
