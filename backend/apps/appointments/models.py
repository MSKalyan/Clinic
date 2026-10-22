"""Patients, consents, appointments and their event history."""
from __future__ import annotations

from django.db import models

from apps.core.constants import (
    AppointmentStatus,
    BookingSource,
    ConsentPurpose,
    ConsentStatus,
)
from apps.core.models import ClinicOwnedModel, TimeStampedModel, UUIDModel


class Patient(ClinicOwnedModel):
    """A patient of a clinic. Uniquely identified inside the clinic by phone."""

    name = models.CharField(max_length=200, blank=True, default="")
    phone = models.CharField(max_length=32, db_index=True)
    preferred_language = models.CharField(max_length=16, blank=True, default="")
    communication_preferences = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "patients"
        constraints = [
            models.UniqueConstraint(fields=["clinic", "phone"], name="uniq_patient_phone_per_clinic")
        ]
        indexes = [models.Index(fields=["clinic", "phone"], name="patient_clinic_phone_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.name or 'Unknown'} ({self.phone})"

    def prefers(self, channel: str) -> bool:
        """Has the patient opted out of ``channel``?"""
        prefs = self.communication_preferences or {}
        return not bool(prefs.get(f"opt_out_{channel}", False))


class PatientConsent(ClinicOwnedModel):
    """A recorded communication permission for a patient."""

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="consents"
    )
    purpose = models.CharField(
        max_length=40, choices=[(p.value, p.value) for p in ConsentPurpose]
    )
    channel = models.CharField(max_length=20)
    consent_status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in ConsentStatus],
        default=ConsentStatus.PENDING,
    )
    captured_at = models.DateTimeField(auto_now_add=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    evidence_reference = models.CharField(max_length=255, blank=True, default="")
    notes = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "patient_consents"
        indexes = [models.Index(fields=["patient", "purpose", "channel"], name="consent_lookup_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.patient_id} {self.purpose}/{self.channel}={self.consent_status}"


class Appointment(ClinicOwnedModel):
    """A booked slot for a patient with a doctor.

    Overlap prevention is enforced by a PostgreSQL exclusion constraint
    (see the ``appointments_conflict_guards`` migration) *and* by the
    booking service, which re-checks inside the transaction.
    """

    doctor = models.ForeignKey(
        "doctors.Doctor", on_delete=models.PROTECT, related_name="appointments"
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, related_name="appointments"
    )
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=30,
        choices=[(s.value, s.value) for s in AppointmentStatus],
        default=AppointmentStatus.BOOKED,
    )
    booking_source = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in BookingSource],
        default=BookingSource.API,
    )
    reference = models.CharField(max_length=24, db_index=True)
    notes = models.TextField(blank=True, default="")
    cancellation_reason = models.CharField(max_length=255, blank=True, default="")
    cancelled_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_appointments",
    )
    rescheduled_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rescheduled_to",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "appointments"
        ordering = ["start_at"]
        indexes = [
            models.Index(fields=["clinic", "start_at"], name="appt_clinic_start_idx"),
            models.Index(fields=["doctor", "start_at"], name="appt_doctor_start_idx"),
            models.Index(fields=["clinic", "status"], name="appt_clinic_status_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.reference} {self.doctor_id} {self.start_at}"

    @property
    def is_occupying(self) -> bool:
        from apps.core.constants import OCCUPYING_STATUSES

        return self.status in OCCUPYING_STATUSES

    def can_transition_to(self, new_status: str) -> bool:
        from apps.core.constants import APPOINTMENT_TRANSITIONS

        allowed = APPOINTMENT_TRANSITIONS.get(AppointmentStatus(self.status), frozenset())
        return AppointmentStatus(new_status) in allowed


class AppointmentEvent(ClinicOwnedModel):
    """Append-only history of everything that happened to an appointment."""

    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=60, db_index=True)
    actor_type = models.CharField(max_length=30, default="system")
    actor_id = models.CharField(max_length=100, blank=True, default="")
    event_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "appointment_events"
        ordering = ["created_at"]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.appointment_id} {self.event_type}"


class ReminderLog(UUIDModel, TimeStampedModel):
    """One scheduled reminder for one appointment.

    The unique ``idempotency_key`` guarantees a reminder is only ever sent
    once, even if the scheduler runs twice or a worker restarts.
    """

    clinic = models.ForeignKey(
        "tenancy.Clinic", on_delete=models.CASCADE, related_name="reminder_logs"
    )
    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name="reminders"
    )
    channel = models.CharField(max_length=20)
    template_id = models.CharField(max_length=80, default="appointment_reminder")
    offset_hours = models.PositiveIntegerField(default=24)
    due_at = models.DateTimeField(db_index=True)
    # The appointment start this reminder was scheduled *for*. It is stored
    # rather than derived from ``due_at`` + offset because ``due_at`` is a
    # scheduling field that a retry or a sweep may legitimately move, while
    # the reminder's identity is "the message about appointment start T".
    scheduled_start_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=20, default="pending", db_index=True)
    provider_message_id = models.CharField(max_length=200, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reminder_logs"
        ordering = ["due_at"]
        indexes = [
            models.Index(fields=["clinic", "status", "due_at"], name="reminder_scan_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"Reminder({self.idempotency_key} {self.status})"
