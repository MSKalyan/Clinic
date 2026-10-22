"""Tool implementations.

Each handler receives ``(clinic, arguments, context)`` where ``context``
carries the actor (staff user or service token), the interaction id used for
idempotency, and the caller's phone number when known.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from django.utils import timezone

from apps.ai_tools.registry import Tool, register
from apps.ai_tools.safety import contains_clinical_request, detect_emergency
from apps.appointments.models import Appointment, Patient
from apps.appointments.services.availability import AvailabilityService
from apps.appointments.services.booking import BookingService, get_or_create_patient
from apps.core.constants import (
    AppointmentStatus,
    BookingSource,
    ConsentPurpose,
    FollowUpTaskType,
    TaskPriority,
)
from apps.core.exceptions import DomainError
from apps.core.timeutils import to_clinic_local
from apps.core.utils import normalise_phone
from apps.doctors.models import Doctor
from apps.doctors.services.status import DoctorStatusService

logger = logging.getLogger("apps.ai_tools.handlers")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_datetime(value: Any, *, end_of_day: bool = False) -> datetime:
    """Accept an ISO date or datetime and return an aware UTC datetime."""
    if value in (None, ""):
        raise DomainError("A date or datetime is required.", code="invalid_datetime")
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            if len(text) == 10:
                day = date.fromisoformat(text)
                parsed = datetime.combine(day, time(23, 59) if end_of_day else time(0, 0))
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DomainError(
                f"Could not understand the date '{value}'.", code="invalid_datetime"
            ) from exc
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _resolve_doctors(clinic, arguments: dict[str, Any]) -> list[Doctor]:  # noqa: ANN001
    doctors = Doctor.objects.filter(clinic=clinic, is_active=True)
    doctor_id = arguments.get("doctor_id")
    if doctor_id:
        doctors = doctors.filter(pk=doctor_id)
    name = arguments.get("doctor_name")
    if name:
        doctors = doctors.filter(name__icontains=name)
    specialization = arguments.get("specialization")
    if specialization:
        doctors = doctors.filter(specialization__icontains=specialization)
    return list(doctors.select_related("clinic"))


def _patient_for(clinic, arguments: dict[str, Any], *, create: bool = True) -> Patient:
    """Find (or create) the patient from a phone number in the arguments.

    ``create=False`` is used for lookups such as cancelling an appointment,
    so that an unknown caller does not create a junk patient record.
    """
    phone = arguments.get("patient_phone") or arguments.get("phone")
    if not phone:
        raise DomainError(
            "A patient phone number is required to identify the patient.",
            code="patient_identification_required",
        )
    normalised = normalise_phone(phone)
    if not normalised:
        raise DomainError(
            "That phone number does not look right. Could you confirm it?",
            code="invalid_phone",
        )
    if not create:
        patient = Patient.objects.filter(clinic=clinic, phone=normalised).first()
        if patient is None:
            raise DomainError(
                "I could not find any appointments on that number.",
                code="patient_not_found",
            )
        return patient
    patient, _ = get_or_create_patient(
        clinic=clinic,
        phone=normalised,
        name=(arguments.get("patient_name") or "")[:200],
        preferred_language=arguments.get("preferred_language") or "",
    )
    return patient


def _patient_appointments(clinic, patient: Patient) -> list[Appointment]:
    return list(
        Appointment.objects.filter(clinic=clinic, patient=patient)
        .exclude(status__in=[AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED])
        .select_related("doctor", "patient")
        .order_by("start_at")
    )


def _appointment_for(clinic, arguments: dict[str, Any]) -> Appointment:
    """Resolve the appointment a patient-facing request refers to.

    A patient may only reach their *own* appointments: the appointment must
    belong to the patient identified by the phone number in the request.
    """
    patient = _patient_for(clinic, arguments, create=False)
    appointment_id = arguments.get("appointment_id")
    appointments = _patient_appointments(clinic, patient)
    if appointment_id:
        for appointment in appointments:
            if str(appointment.id) == str(appointment_id):
                return appointment
        raise DomainError(
            "I could not find that appointment on your record.",
            code="appointment_not_found",
        )
    if not appointments:
        raise DomainError(
            "I could not find an upcoming appointment on your record.",
            code="appointment_not_found",
        )
    return appointments[0]


def _serialise_appointment(appointment: Appointment) -> dict[str, Any]:
    return {
        "appointment_id": str(appointment.id),
        "reference": appointment.reference,
        "status": appointment.status,
        "start_at": appointment.start_at.isoformat(),
        "end_at": appointment.end_at.isoformat(),
        "doctor_name": appointment.doctor.name,
        "specialization": appointment.doctor.specialization,
    }


# ---------------------------------------------------------------------------
# Tool: get_doctor_availability
# ---------------------------------------------------------------------------
def get_doctor_availability(clinic, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Report the live availability of a doctor's schedule."""
    doctors = _resolve_doctors(clinic, arguments)
    if not doctors:
        return {"doctors": [], "message": "No matching doctor is available at this clinic."}

    results = []
    for doctor in doctors:
        snapshot = DoctorStatusService.get_current(doctor)
        results.append(
            {
                "doctor_id": str(doctor.id),
                "doctor_name": doctor.name,
                "specialization": doctor.specialization,
                "status": snapshot.status,
                "status_is_stale": snapshot.is_stale,
                "last_confirmed_at": (
                    snapshot.last_confirmed_at.isoformat() if snapshot.last_confirmed_at else None
                ),
                "expected_arrival_at": (
                    snapshot.expected_arrival_at.isoformat()
                    if snapshot.expected_arrival_at
                    else None
                ),
                "expected_departure_at": (
                    snapshot.expected_departure_at.isoformat()
                    if snapshot.expected_departure_at
                    else None
                ),
                "next_available": None,
            }
        )
    return {
        "doctors": results,
        "note": (
            "Status 'present' means the doctor has explicitly confirmed presence. "
            "A scheduled shift alone does not confirm the doctor has arrived."
        ),
    }


# ---------------------------------------------------------------------------
# Tool: get_available_appointment_slots
# ---------------------------------------------------------------------------
def get_available_appointment_slots(clinic, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Return bookable slots."""
    doctors = _resolve_doctors(clinic, arguments)
    if not doctors:
        return {"slots": [], "message": "No matching doctor is available at this clinic."}

    on_date = arguments.get("date")
    day = None
    if on_date:
        try:
            day = date.fromisoformat(str(on_date)[:10])
        except ValueError as exc:
            raise DomainError(
                f"Could not understand the date '{on_date}'.", code="invalid_date"
            ) from exc

    service = AvailabilityService(clinic)
    slots = service.slots(
        doctors=doctors,
        on_date=day,
        duration_minutes=arguments.get("duration_minutes"),
    )

    limit = int(arguments.get("limit") or 12)
    return {
        "slots": [slot.as_dict() for slot in slots[:limit]],
        "total_available": len(slots),
        "date": day.isoformat() if day else None,
    }


# ---------------------------------------------------------------------------
# Tool: book_appointment
# ---------------------------------------------------------------------------
def book_appointment(clinic, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Book an appointment. The booking is confirmed only after it commits."""
    start_at = _parse_datetime(arguments.get("start_at"))
    doctor_id = arguments.get("doctor_id")
    if not doctor_id:
        raise DomainError("A doctor must be selected before booking.", code="doctor_required")

    doctor = (
        Doctor.objects.filter(clinic=clinic, pk=doctor_id, is_active=True)
        .select_related("clinic")
        .first()
    )
    if doctor is None:
        raise DomainError("That doctor is not available.", code="doctor_not_found")

    patient = _patient_for(clinic, arguments)

    if context.get("emergency_detected"):
        raise DomainError(
            "This request needs to be handled by clinic staff straight away.",
            code="emergency_detected",
        )

    appointment = BookingService.book(
        clinic=clinic,
        doctor=doctor,
        patient=patient,
        start_at=start_at,
        source=context.get("booking_source", BookingSource.AGENT),
        duration_minutes=arguments.get("duration_minutes"),
        notes=(arguments.get("notes") or "")[:2000],
        idempotency_key=context.get("idempotency_key"),
        actor=context.get("actor"),
        actor_type=context.get("actor_type", "agent"),
    )
    local_start = to_clinic_local(appointment.start_at, clinic)
    return {
        "booked": True,
        "appointment": _serialise_appointment(appointment),
        "message": (
            f"Your appointment with {doctor.name} is confirmed for "
            f"{local_start.strftime('%d %b %Y, %I:%M %p')}."
        ),
        "display_start": local_start.isoformat(),
    }


# ---------------------------------------------------------------------------
# Tool: reschedule_appointment
# ---------------------------------------------------------------------------
def reschedule_appointment(clinic, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Move an appointment to a new time."""
    appointment = _appointment_for(clinic, arguments)
    new_start = _parse_datetime(arguments.get("new_start_at"))
    appointment = BookingService.reschedule(
        appointment=appointment,
        new_start_at=new_start,
        actor=context.get("actor"),
        actor_type=context.get("actor_type", "agent"),
        duration_minutes=arguments.get("duration_minutes"),
    )
    return {
        "rescheduled": True,
        "appointment": _serialise_appointment(appointment),
    }


# ---------------------------------------------------------------------------
# Tool: cancel_appointment
# ---------------------------------------------------------------------------
def cancel_appointment(clinic, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Cancel an appointment."""
    appointment = _appointment_for(clinic, arguments)
    reason = arguments.get("reason") or "Cancelled at the patient's request"
    appointment = BookingService.cancel(
        appointment=appointment,
        reason=reason,
        actor=context.get("actor"),
        actor_type=context.get("actor_type", "agent"),
        force=bool(context.get("force")),
    )
    return {
        "cancelled": True,
        "appointment": _serialise_appointment(appointment),
    }


# ---------------------------------------------------------------------------
# Tool: create_follow_up_request
# ---------------------------------------------------------------------------
def create_follow_up_request(clinic, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Create a task for clinic staff."""
    from apps.conversations.services.followups import FollowUpService

    patient = None
    if arguments.get("patient_phone"):
        try:
            patient = _patient_for(clinic, arguments)
        except DomainError:
            patient = None

    interaction_id = context.get("interaction_id") or "manual"
    dedupe = FollowUpService.dedupe_key(
        "agent_follow_up", clinic.id, interaction_id, arguments.get("task_type", "general")
    )
    task = FollowUpService.create_task(
        clinic=clinic,
        task_type=FollowUpTaskType.HUMAN_ASSISTANCE
        if arguments.get("request_human_assistance")
        else FollowUpTaskType.UNRESOLVED_REQUEST,
        dedupe_key=dedupe,
        patient=patient,
        priority=arguments.get("priority") or TaskPriority.NORMAL,
        due_in_minutes=int(arguments.get("due_in_minutes") or 120),
        notes=(arguments.get("notes") or "")[:2000],
    )
    return {
        "created": True,
        "task_id": str(task.id),
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "message": "A member of the clinic team will get in touch.",
    }


# ---------------------------------------------------------------------------
# Tool: request_human_assistance
# ---------------------------------------------------------------------------
def request_human_assistance(clinic, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Hand the conversation to a human."""
    result = create_follow_up_request(
        clinic,
        {
            **arguments,
            "request_human_assistance": True,
            "priority": arguments.get("priority") or TaskPriority.HIGH,
        },
        context,
    )
    result["escalated"] = True
    result["message"] = (
        "I have asked a member of the clinic team to call you back. "
        "This assistant is automated and cannot provide medical advice."
    )
    return result


# ---------------------------------------------------------------------------
# Tool: update_doctor_status (staff only)
# ---------------------------------------------------------------------------
def update_doctor_status(clinic, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Record a doctor's live status. Staff only -- never a service token."""
    from apps.doctors.models import STATUS_SOURCE_VOICE

    doctor_id = arguments.get("doctor_id")
    doctor = (
        Doctor.objects.filter(clinic=clinic, pk=doctor_id).select_related("clinic").first()
    )
    if doctor is None:
        raise DomainError("That doctor is not on this clinic's roster.", code="doctor_not_found")

    actor = context.get("actor")
    role = context.get("role", "")
    if role == "doctor":
        actor_doctor = getattr(actor, "doctor_profile", None) if actor else None
        if actor_doctor is None or str(actor_doctor.id) != str(doctor.id):
            raise DomainError(
                "You can only update your own availability.",
                code="not_your_doctor",
                status_code=403,
            )

    status = arguments.get("status")
    source = arguments.get("source") or STATUS_SOURCE_VOICE
    expected_arrival = arguments.get("expected_arrival_at")
    expected_departure = arguments.get("expected_departure_at")

    snapshot = DoctorStatusService.record(
        doctor=doctor,
        status=status,
        source=source,
        actor=actor,
        expected_arrival_at=_parse_datetime(expected_arrival) if expected_arrival else None,
        expected_departure_at=(
            _parse_datetime(expected_departure) if expected_departure else None
        ),
        notes=arguments.get("notes") or "",
    )
    return {"updated": True, "status": snapshot.as_dict()}


# ---------------------------------------------------------------------------
# Tool: flag_emergency
# ---------------------------------------------------------------------------
def flag_emergency(clinic, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Raise the clinic's safety response for emergency-like language."""
    from apps.ai_tools.safety import safety_response

    policy = clinic.escalation_policy()
    text = arguments.get("text") or ""
    detected = detect_emergency(text, policy.get("emergency_keywords"))
    if not detected:
        return {"emergency": False}
    return {
        "emergency": True,
        "message": safety_response(),
        "clinical_request": contains_clinical_request(text),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
register(
    Tool(
        name="get_doctor_availability",
        description=(
            "Report whether a doctor is present, running late, unavailable or on leave, "
            "and when they are expected."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string"},
                "doctor_name": {"type": "string"},
                "specialization": {"type": "string"},
            },
        },
        handler=get_doctor_availability,
        tags=("availability",),
    )
)

register(
    Tool(
        name="get_available_appointment_slots",
        description="List the appointment slots a patient can book.",
        input_schema={
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string"},
                "specialization": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "duration_minutes": {"type": "integer"},
                "limit": {"type": "integer"},
            },
        },
        handler=get_available_appointment_slots,
        tags=("availability", "booking"),
    )
)

register(
    Tool(
        name="book_appointment",
        description="Book an appointment for a patient with a doctor.",
        input_schema={
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string"},
                "start_at": {"type": "string", "description": "ISO-8601 datetime"},
                "patient_phone": {"type": "string"},
                "patient_name": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["doctor_id", "start_at", "patient_phone"],
        },
        handler=book_appointment,
        idempotent=True,
        tags=("booking",),
    )
)

register(
    Tool(
        name="reschedule_appointment",
        description="Move an existing appointment to a new time.",
        input_schema={
            "type": "object",
            "properties": {
                "appointment_id": {"type": "string"},
                "new_start_at": {"type": "string"},
                "patient_phone": {"type": "string"},
            },
            "required": ["new_start_at", "patient_phone"],
        },
        handler=reschedule_appointment,
        tags=("booking",),
    )
)

register(
    Tool(
        name="cancel_appointment",
        description="Cancel an existing appointment.",
        input_schema={
            "type": "object",
            "properties": {
                "appointment_id": {"type": "string"},
                "patient_phone": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["patient_phone"],
        },
        handler=cancel_appointment,
        tags=("booking",),
    )
)

register(
    Tool(
        name="create_follow_up_request",
        description="Create a task for the clinic team to follow up.",
        input_schema={
            "type": "object",
            "properties": {
                "patient_phone": {"type": "string"},
                "notes": {"type": "string"},
                "priority": {"type": "string"},
            },
        },
        handler=create_follow_up_request,
        tags=("escalation",),
    )
)

register(
    Tool(
        name="request_human_assistance",
        description="Ask a human member of staff to take over.",
        input_schema={
            "type": "object",
            "properties": {
                "patient_phone": {"type": "string"},
                "notes": {"type": "string"},
                "priority": {"type": "string"},
            },
        },
        handler=request_human_assistance,
        tags=("escalation",),
    )
)

register(
    Tool(
        name="update_doctor_status",
        description=(
            "Record a doctor's live status (present, running late, unavailable, on leave). "
            "Only an authenticated member of the clinic team may call this."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": [
                        "present",
                        "running_late",
                        "unavailable",
                        "on_leave",
                        "finished_for_day",
                    ],
                },
                "expected_arrival_at": {"type": "string"},
                "expected_departure_at": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["doctor_id", "status"],
        },
        handler=update_doctor_status,
        staff_only=True,
        tags=("availability", "staff"),
    )
)

register(
    Tool(
        name="flag_emergency",
        description=(
            "Check whether the caller's words indicate a medical emergency and return "
            "the clinic's approved safety response."
        ),
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=flag_emergency,
        tags=("safety",),
    )
)
