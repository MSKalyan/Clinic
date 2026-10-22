"""Doctor status state machine.

Implements PRD section 6:

* precedence between an explicit status and the recurring rota;
* freshness/staleness detection with per-clinic, per-status thresholds;
* an immutable event history that is never rewritten;
* concurrency-safe updates to the "current" pointer.

The ``present`` status is an explicit operational assertion by an authorised
human or integration. It is never inferred from a rota.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.constants import DoctorStatus, InternalEventType
from apps.core.models import OutboxEvent
from apps.doctors.models import Doctor, DoctorStatusCurrent, DoctorStatusEvent

logger = logging.getLogger("apps.doctors.status")


@dataclass(frozen=True)
class StatusSnapshot:
    """What the rest of the system should believe about a doctor right now."""

    doctor_id: Any
    doctor_name: str
    status: str
    #: The status as last recorded (may be stale).
    recorded_status: str
    is_stale: bool
    last_confirmed_at: datetime | None
    effective_from: datetime | None
    expected_arrival_at: datetime | None
    expected_departure_at: datetime | None
    source: str
    version: int
    notes: str = ""

    @property
    def is_present(self) -> bool:
        return self.status in {DoctorStatus.PRESENT, DoctorStatus.RUNNING_LATE}

    @property
    def blocks_booking(self) -> bool:
        return self.status in {
            DoctorStatus.ON_LEAVE,
            DoctorStatus.UNAVAILABLE,
            DoctorStatus.FINISHED_FOR_DAY,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "doctor_id": str(self.doctor_id),
            "doctor_name": self.doctor_name,
            "status": self.status,
            "recorded_status": self.recorded_status,
            "is_stale": self.is_stale,
            "last_confirmed_at": self.last_confirmed_at,
            "effective_from": self.effective_from,
            "expected_arrival_at": self.expected_arrival_at,
            "expected_departure_at": self.expected_departure_at,
            "source": self.source,
            "version": self.version,
            "notes": self.notes,
        }


class DoctorStatusService:
    """Read and write doctor availability."""

    @staticmethod
    def freshness_minutes(clinic, status: str) -> int:  # noqa: ANN001
        thresholds = clinic.status_freshness_minutes()
        return int(thresholds.get(status, 0))

    @classmethod
    def is_stale(cls, clinic, snapshot_status: str, last_confirmed_at: datetime | None) -> bool:  # noqa: ANN001
        if last_confirmed_at is None:
            return True
        minutes = cls.freshness_minutes(clinic, snapshot_status)
        if minutes <= 0:
            return False
        age = timezone.now() - last_confirmed_at
        return age.total_seconds() > minutes * 60

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    @classmethod
    def record(
        cls,
        *,
        doctor: Doctor,
        status: str,
        source: str,
        actor=None,
        actor_identifier: str = "",
        expected_arrival_at: datetime | None = None,
        expected_departure_at: datetime | None = None,
        effective_from: datetime | None = None,
        effective_until: datetime | None = None,
        notes: str = "",
    ) -> StatusSnapshot:
        """Record a status change and update the current pointer atomically."""
        if status not in {s.value for s in DoctorStatus}:
            raise ValueError(f"unknown doctor status: {status}")

        effective_from = effective_from or timezone.now()
        clinic = doctor.clinic

        with transaction.atomic():
            current, _ = DoctorStatusCurrent.objects.select_for_update().get_or_create(
                clinic=clinic,
                doctor=doctor,
                defaults={"current_status": DoctorStatus.UNKNOWN},
            )
            next_version = current.version + 1
            previous_status = current.current_status

            event = DoctorStatusEvent.objects.create(
                clinic=clinic,
                doctor=doctor,
                status=status,
                effective_from=effective_from,
                effective_until=effective_until,
                expected_arrival_at=expected_arrival_at,
                expected_departure_at=expected_departure_at,
                source=source,
                updated_by=actor if getattr(actor, "pk", None) else None,
                updated_by_identifier=actor_identifier or "",
                notes=notes[:500],
                sequence=next_version,
            )

            current.current_status = status
            current.current_event = event
            current.last_confirmed_at = effective_from
            current.expected_arrival_at = expected_arrival_at
            current.expected_departure_at = expected_departure_at
            current.source = source
            current.version = next_version
            current.save(
                update_fields=[
                    "current_status",
                    "current_event",
                    "last_confirmed_at",
                    "expected_arrival_at",
                    "expected_departure_at",
                    "source",
                    "version",
                    "updated_at",
                ]
            )

            OutboxEvent.objects.create(
                clinic=clinic,
                event_type=InternalEventType.DOCTOR_STATUS_CHANGED,
                payload={
                    "doctor_id": str(doctor.id),
                    "doctor_name": doctor.name,
                    "status": status,
                    "previous_status": previous_status,
                    "source": source,
                    "expected_arrival_at": (
                        expected_arrival_at.isoformat() if expected_arrival_at else None
                    ),
                    "effective_from": effective_from.isoformat(),
                    "event_id": str(event.id),
                    "version": next_version,
                },
            )

        logger.info(
            "doctor status recorded doctor=%s status=%s source=%s version=%s",
            doctor.id,
            status,
            source,
            next_version,
        )
        return cls.get_current(doctor)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @classmethod
    def get_current(cls, doctor: Doctor, *, at: datetime | None = None) -> StatusSnapshot:
        """The status the rest of the system should use right now.

        Applies the precedence rules: a fresh, unexpired explicit update
        wins; a stale or expired explicit update degrades to ``unknown``; with
        no explicit update at all the rota yields ``scheduled``.
        """
        at = at or timezone.now()
        clinic = doctor.clinic
        current = (
            DoctorStatusCurrent.objects.filter(clinic=clinic, doctor=doctor)
            .select_related("current_event")
            .first()
        )

        if current is None or current.current_event is None:
            return StatusSnapshot(
                doctor_id=doctor.id,
                doctor_name=doctor.name,
                status=cls._rota_fallback(doctor, at),
                recorded_status=DoctorStatus.UNKNOWN,
                is_stale=False,
                last_confirmed_at=None,
                effective_from=None,
                expected_arrival_at=None,
                expected_departure_at=None,
                source="",
                version=0,
            )

        event = current.current_event
        expired = event.effective_until is not None and event.effective_until <= at
        stale = cls.is_stale(clinic, current.current_status, current.last_confirmed_at)

        if expired or stale:
            status = DoctorStatus.UNKNOWN
        else:
            status = current.current_status

        return StatusSnapshot(
            doctor_id=doctor.id,
            doctor_name=doctor.name,
            status=status,
            recorded_status=current.current_status,
            is_stale=stale or expired,
            last_confirmed_at=current.last_confirmed_at,
            effective_from=event.effective_from,
            expected_arrival_at=current.expected_arrival_at,
            expected_departure_at=current.expected_departure_at,
            source=current.source,
            version=current.version,
            notes=event.notes,
        )

    @staticmethod
    def _rota_fallback(doctor: Doctor, at: datetime) -> str:
        """What the rota alone implies -- never ``present``.

        A scheduled shift does not prove a doctor has arrived (PRD 6.3.2).
        """
        from apps.core.timeutils import clinic_zone, to_clinic_local

        local = to_clinic_local(at, doctor.clinic)
        weekday = local.weekday()
        schedules = doctor.schedules.filter(is_active=True, weekday=weekday)
        for schedule in schedules:
            if not schedule.applies_on(local.date()):
                continue
            if schedule.start_time <= local.time() <= schedule.end_time:
                return DoctorStatus.SCHEDULED
        return DoctorStatus.UNKNOWN

    @classmethod
    def get_snapshots(cls, doctors) -> list[StatusSnapshot]:  # noqa: ANN001
        return [cls.get_current(doctor) for doctor in doctors]
