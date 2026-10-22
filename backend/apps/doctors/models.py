"""Doctors, recurring schedules, schedule exceptions and status events."""
from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.constants import DoctorStatus
from apps.core.models import ClinicOwnedModel

#: Where a status update came from. Recorded for every event so the audit
#: trail can distinguish a human assertion from an automated inference.
STATUS_SOURCE_DASHBOARD = "dashboard"
STATUS_SOURCE_VOICE = "voice"
STATUS_SOURCE_WHATSAPP = "whatsapp"
STATUS_SOURCE_TELEPHONY = "telephony"
STATUS_SOURCE_INTEGRATION = "integration"
STATUS_SOURCE_SCHEDULER = "scheduler"
STATUS_SOURCE_SYSTEM = "system"

STATUS_SOURCES = [
    STATUS_SOURCE_DASHBOARD,
    STATUS_SOURCE_VOICE,
    STATUS_SOURCE_WHATSAPP,
    STATUS_SOURCE_TELEPHONY,
    STATUS_SOURCE_INTEGRATION,
    STATUS_SOURCE_SCHEDULER,
    STATUS_SOURCE_SYSTEM,
]

#: Schedule exception kinds.
EXCEPTION_UNAVAILABLE = "unavailable"
EXCEPTION_AVAILABLE = "available"


class Doctor(ClinicOwnedModel):
    """A doctor practising at a clinic."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120)
    specialization = models.CharField(max_length=160, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    languages = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="doctor_profiles",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "doctors"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["clinic", "slug"], name="uniq_doctor_slug_per_clinic")
        ]
        indexes = [models.Index(fields=["clinic", "is_active"], name="doctor_clinic_active_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"Dr {self.name} ({self.clinic_id})"


class DoctorSchedule(ClinicOwnedModel):
    """A recurring weekly working window for a doctor."""

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="schedules")
    #: Monday == 0 ... Sunday == 6 (matches ``date.weekday()``).
    weekday = models.PositiveIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(6)]
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    effective_from = models.DateField(null=True, blank=True)
    effective_until = models.DateField(null=True, blank=True)
    slot_interval_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "doctor_schedules"
        constraints = [
            models.CheckConstraint(
                check=models.Q(start_time__lt=models.F("end_time")),
                name="doctor_schedule_start_before_end",
            )
        ]
        indexes = [
            models.Index(fields=["doctor", "weekday"], name="schedule_doctor_weekday_idx")
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.doctor_id} {self.weekday} {self.start_time}-{self.end_time}"

    def applies_on(self, day) -> bool:  # noqa: ANN001
        if self.effective_from and day < self.effective_from:
            return False
        if self.effective_until and day > self.effective_until:
            return False
        return True


class DoctorScheduleException(ClinicOwnedModel):
    """An ad-hoc override for a specific date.

    ``unavailable`` closes a window that would otherwise be open;
    ``available`` opens an extra one.
    """

    doctor = models.ForeignKey(
        Doctor, on_delete=models.CASCADE, related_name="schedule_exceptions"
    )
    date = models.DateField(db_index=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    kind = models.CharField(
        max_length=20,
        choices=[(EXCEPTION_UNAVAILABLE, "Unavailable"), (EXCEPTION_AVAILABLE, "Available")],
        default=EXCEPTION_UNAVAILABLE,
    )
    reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "doctor_schedule_exceptions"
        indexes = [models.Index(fields=["doctor", "date"], name="exception_doctor_date_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.doctor_id} {self.date} {self.kind}"


class DoctorStatusEvent(ClinicOwnedModel):
    """An immutable, timestamped assertion about a doctor's status."""

    doctor = models.ForeignKey(
        Doctor, on_delete=models.CASCADE, related_name="status_events"
    )
    status = models.CharField(
        max_length=20, choices=[(s.value, s.value) for s in DoctorStatus]
    )
    effective_from = models.DateTimeField(db_index=True)
    effective_until = models.DateTimeField(null=True, blank=True)
    expected_arrival_at = models.DateTimeField(null=True, blank=True)
    expected_departure_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=30, choices=[(s, s) for s in STATUS_SOURCES])
    updated_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="doctor_status_events",
    )
    #: Identifier of a non-human actor (provider, integration).
    updated_by_identifier = models.CharField(max_length=200, blank=True, default="")
    notes = models.CharField(max_length=500, blank=True, default="")
    sequence = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "doctor_status_events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "-created_at"], name="status_event_doctor_idx"),
            models.Index(fields=["clinic", "status"], name="status_event_clinic_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.doctor_id}: {self.status} @ {self.effective_from}"

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone

        if self.effective_until is None:
            return False
        return self.effective_until <= timezone.now()


class DoctorStatusCurrent(ClinicOwnedModel):
    """The current status pointer for a doctor.

    Maintained transactionally (row locked with ``SELECT ... FOR UPDATE``)
    so that concurrent updates cannot interleave and lose a status change.
    """

    doctor = models.OneToOneField(
        Doctor, on_delete=models.CASCADE, related_name="status_current"
    )
    current_status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in DoctorStatus],
        default=DoctorStatus.UNKNOWN,
    )
    last_confirmed_at = models.DateTimeField(null=True, blank=True)
    current_event = models.ForeignKey(
        DoctorStatusEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    expected_arrival_at = models.DateTimeField(null=True, blank=True)
    expected_departure_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=30, blank=True, default="")
    version = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "doctor_status_current"
        constraints = [
            models.UniqueConstraint(fields=["clinic", "doctor"], name="uniq_status_current")
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.doctor_id}: {self.current_status} (v{self.version})"
