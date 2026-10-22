"""AI tool permissions, tenant isolation and safety.

The assistant is the part of the system that is hardest to reason about,
because it is driven by text. Three guarantees are tested here:

* **Permissions.** A provider service token may call the patient-facing
  tools, but it must not be able to change clinic state on a human's
  instruction (``staff_only``), and a staff member's role is what decides
  whether a call is allowed at all.
* **Tenant isolation.** A tool call is bound to the tenant of the
  credential that made it. Nothing a caller sends -- a doctor id, a phone
  number, a header -- can move the call into another clinic.
* **Safety.** The assistant is administrative, not clinical. Emergency
  language has to produce the clinic's safety response, and the response
  has to identify itself as automated.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai_tools.safety import (
    contains_clinical_request,
    detect_emergency,
    safety_response,
)

TOOLS_URL = "/api/v1/tools/"
INVOKE_URL = "/api/v1/tools/{tool}/invoke/"


def invoke(client, tool, arguments, **extra):
    payload = {"arguments": arguments}
    payload.update(extra)
    return client.post(INVOKE_URL.format(tool=tool), payload, format="json")


def make_doctor(clinic, name, slug):
    """Create a doctor inside another tenant's scope.

    With Row Level Security on, a write that carries a foreign
    ``clinic_id`` is rejected by the database, so the row has to be written
    from inside that tenant's scope.
    """
    from apps.core.rls import rls_scope
    from apps.doctors.models import Doctor

    with rls_scope(str(clinic.id)):
        return Doctor.objects.create(clinic=clinic, name=name, slug=slug)


# ---------------------------------------------------------------------------
# Service tokens vs staff
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_service_token_cannot_call_a_staff_only_tool(token_client, doctor):
    """A provider credential is not a human instruction."""
    response = invoke(
        token_client,
        "update_doctor_status",
        {"doctor_id": str(doctor.id), "status": "present"},
    )

    assert response.status_code == 403
    assert response.data["error"]["code"] == "tool_forbidden"


@pytest.mark.django_db
def test_a_service_token_does_not_even_see_the_staff_only_tools(token_client):
    """The catalogue a provider is offered excludes staff-only tools."""
    response = token_client.get(TOOLS_URL)

    assert response.status_code == 200
    names = {tool["name"] for tool in response.data["tools"]}
    assert "update_doctor_status" not in names
    assert "book_appointment" in names


@pytest.mark.django_db
def test_a_staff_member_can_call_a_staff_only_tool(auth_client, doctor):
    """The receptionist on duty may record a doctor's status."""
    response = invoke(
        auth_client,
        "update_doctor_status",
        {"doctor_id": str(doctor.id), "status": "present"},
    )

    assert response.status_code == 200, response.data
    assert response.data["updated"] is True
    assert response.data["status"]["status"] == "present"


@pytest.mark.django_db
def test_a_caller_without_a_clinic_membership_gets_no_tools(staff_user):
    """Authentication alone is not a clinic context."""
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    token = RefreshToken.for_user(staff_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    response = client.get(TOOLS_URL)

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_tool_call_is_audited_without_the_patient_content(
    auth_client, doctor, slot_time, as_clinic, clinic
):
    """The audit trail records what happened, and nothing about the patient."""
    from apps.core.models import AuditLog

    response = invoke(
        auth_client,
        "book_appointment",
        {
            "doctor_id": str(doctor.id),
            "start_at": slot_time.isoformat(),
            "patient_phone": "+919000100001",
        },
    )
    assert response.status_code == 200, response.data

    # The request clears the Row Level Security scope when it finishes, so
    # the audit rows have to be read back inside the clinic's scope.
    with as_clinic(clinic):
        entry = AuditLog.objects.filter(action="book").first()

    assert entry is not None
    assert entry.metadata["tool"] == "book_appointment"
    assert "+919000100001" not in str(entry.metadata)


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_service_token_cannot_use_a_header_to_reach_another_clinic(
    token_client, other_clinic, doctor
):
    """The clinic header cannot move a service token to another tenant.

    The token *is* the tenant binding, so an ``X-Clinic-Id`` header naming
    a different clinic is ignored rather than honoured.
    """
    make_doctor(other_clinic, "Hidden Doctor", "hidden-doctor-header")

    token_client.defaults["HTTP_X_CLINIC_ID"] = str(other_clinic.id)

    response = invoke(token_client, "get_doctor_availability", {})

    assert response.status_code == 200, response.data
    names = {entry["doctor_name"] for entry in response.data["doctors"]}
    assert doctor.name in names
    assert "Hidden Doctor" not in names


@pytest.mark.django_db
def test_a_tool_cannot_see_another_tenants_doctors(token_client, other_clinic):
    """The other tenant's roster is invisible to the tool."""
    make_doctor(other_clinic, "Hidden Doctor", "hidden-doctor-roster")

    response = invoke(token_client, "get_doctor_availability", {})

    assert response.status_code == 200
    names = {entry["doctor_name"] for entry in response.data["doctors"]}
    assert "Hidden Doctor" not in names


@pytest.mark.django_db
def test_a_tool_cannot_book_with_another_tenants_doctor(token_client, other_clinic, slot_time):
    """Passing a foreign doctor id does not book a foreign doctor."""
    hidden = make_doctor(other_clinic, "Hidden Doctor", "hidden-doctor-book")

    response = invoke(
        token_client,
        "book_appointment",
        {
            "doctor_id": str(hidden.id),
            "start_at": slot_time.isoformat(),
            "patient_phone": "+919000100001",
        },
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "doctor_not_found"


@pytest.mark.django_db
def test_a_tool_cannot_cancel_another_tenants_appointment(token_client, other_appointment):
    """A phone number from another tenant resolves to nothing."""
    response = invoke(
        token_client,
        "cancel_appointment",
        {"patient_phone": other_appointment.patient.phone, "reason": "not mine"},
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "patient_not_found"


@pytest.mark.django_db
def test_a_patient_only_reaches_their_own_appointments(
    token_client, scoped, doctor, patient, slot_time
):
    """A caller may not name somebody else's appointment."""
    from apps.appointments.models import Patient
    from apps.appointments.services.booking import BookingService

    mine = BookingService.book(
        clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
    )
    someone_else = Patient.objects.create(
        clinic=scoped, name="Someone Else", phone="+919000100099"
    )
    theirs = BookingService.book(
        clinic=scoped,
        doctor=doctor,
        patient=someone_else,
        start_at=slot_time + timedelta(days=7),
    )

    response = invoke(
        token_client,
        "cancel_appointment",
        {
            "patient_phone": patient.phone,
            "appointment_id": str(theirs.id),
            "reason": "not mine",
        },
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "appointment_not_found"
    assert mine.status == "booked"


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_emergency_language_produces_the_safety_response(token_client):
    """Emergency wording is routed to the safety policy, not to booking."""
    response = invoke(
        token_client,
        "flag_emergency",
        {"text": "I have severe chest pain and cannot breathe"},
    )

    assert response.status_code == 200, response.data
    assert response.data["emergency"] is True
    message = response.data["message"]
    assert "112" in message
    assert "emergency" in message.lower()


@pytest.mark.django_db
def test_ordinary_booking_language_is_not_an_emergency(token_client):
    """The safety response must not fire on routine requests."""
    response = invoke(
        token_client,
        "flag_emergency",
        {"text": "I would like to book an appointment with Dr Anita Rao"},
    )

    assert response.status_code == 200
    assert response.data["emergency"] is False
    assert "message" not in response.data


@pytest.mark.django_db
def test_the_safety_response_identifies_the_assistant_as_automated():
    """The assistant always says what it is (PRD 4.7)."""
    message = safety_response()

    assert "automated assistant" in message.lower()
    assert "112" in message


@pytest.mark.django_db
def test_the_safety_response_gives_no_clinical_advice():
    """It must not diagnose, prescribe or dose anything."""
    message = safety_response().lower()

    for forbidden in ("take ", "mg", "prescrib", "diagnos", "dose"):
        assert forbidden not in message


@pytest.mark.django_db
def test_a_clinical_request_is_flagged_alongside_the_emergency(token_client):
    """Asking for a diagnosis is reported, but still not answered."""
    response = invoke(
        token_client,
        "flag_emergency",
        {"text": "chest pain, and what medicine should I take?"},
    )

    assert response.status_code == 200
    assert response.data["emergency"] is True
    assert response.data["clinical_request"] is True


@pytest.mark.django_db
def test_the_emergency_keywords_are_the_clinics_own():
    """Detection is driven by the clinic's configured policy."""
    assert detect_emergency("chest pain") is False
    assert detect_emergency("chest pain", ["chest pain"]) is True
    assert detect_emergency("", ["chest pain"]) is False


@pytest.mark.django_db
def test_a_clinical_request_outside_the_emergency_list_is_still_flagged():
    """A diagnosis request is recognised even without emergency wording."""
    assert contains_clinical_request("can you prescribe me an antibiotic") is True
    assert contains_clinical_request("I need a general medicine appointment") is False


# ---------------------------------------------------------------------------
# Idempotency and argument validation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_booking_through_the_tool_is_idempotent(token_client, doctor, slot_time):
    """A retried tool call does not create a second appointment."""
    payload = {
        "doctor_id": str(doctor.id),
        "start_at": slot_time.isoformat(),
        "patient_phone": "+919000100001",
    }

    first = invoke(token_client, "book_appointment", payload, interaction_id="call-1")
    second = invoke(token_client, "book_appointment", payload, interaction_id="call-1")

    assert first.status_code == 200, first.data
    assert second.status_code == 200, second.data
    assert (
        first.data["appointment"]["appointment_id"]
        == second.data["appointment"]["appointment_id"]
    )


@pytest.mark.django_db
def test_a_missing_required_argument_is_rejected(token_client, doctor):
    response = invoke(token_client, "book_appointment", {"doctor_id": str(doctor.id)})

    assert response.status_code == 400
    assert response.data["error"]["code"] == "missing_arguments"


@pytest.mark.django_db
def test_an_unknown_argument_is_rejected(token_client, doctor):
    """The model cannot smuggle extra fields into a tool call."""
    response = invoke(
        token_client,
        "book_appointment",
        {
            "doctor_id": str(doctor.id),
            "start_at": "2030-01-01T09:00:00+05:30",
            "patient_phone": "+919000100001",
            "clinic_id": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "unknown_arguments"


@pytest.mark.django_db
def test_an_unknown_tool_is_a_404(token_client):
    response = invoke(token_client, "delete_everything", {})

    assert response.status_code == 404
