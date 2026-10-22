"""Tenant isolation at the API boundary (PRD 3).

A staff member of clinic A must not be able to see or touch clinic B's
data, no matter what they put in the request. The tenant comes from the
``X-Clinic-Id`` header, and that header is only honoured when the caller
has an *active membership* in that clinic.
"""
from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_a_member_only_sees_their_own_clinics_appointments(
    auth_client, clinic, other_clinic, doctor, patient, other_appointment
):
    """Bookings made in the other clinic are invisible."""
    response = auth_client.get("/api/v1/appointments/")

    assert response.status_code == 200
    assert response.data["count"] == 0


@pytest.mark.django_db
def test_a_member_cannot_read_another_clinics_appointment_by_id(
    auth_client, clinic, other_clinic, other_appointment
):
    response = auth_client.get(f"/api/v1/appointments/{other_appointment.id}/")

    assert response.status_code in (403, 404)


@pytest.mark.django_db
def test_a_member_cannot_cancel_another_clinics_appointment(
    auth_client, clinic, other_clinic, other_appointment
):
    from apps.core.rls import rls_scope

    response = auth_client.post(
        f"/api/v1/appointments/{other_appointment.id}/cancel/",
        {"reason": "nope"},
        format="json",
    )

    assert response.status_code in (403, 404)

    # The row is read back inside the *other* tenant's scope: outside it the
    # Row Level Security policy hides the appointment completely, which is
    # exactly the behaviour we want.
    with rls_scope(str(other_clinic.id)):
        other_appointment.refresh_from_db()
        assert other_appointment.status == "booked"


@pytest.mark.django_db
def test_the_clinic_header_must_match_a_real_membership(
    api_client, staff_user, membership, clinic, other_clinic
):
    """Pointing the header at a clinic you do not belong to is refused."""
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(staff_user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    api_client.defaults["HTTP_X_CLINIC_ID"] = str(other_clinic.id)

    response = api_client.get("/api/v1/appointments/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_missing_clinic_header_is_refused(auth_client, clinic):
    auth_client.defaults.pop("HTTP_X_CLINIC_ID", None)

    response = auth_client.get("/api/v1/appointments/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_non_uuid_clinic_header_is_refused(api_client, staff_user, membership):
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(staff_user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    api_client.defaults["HTTP_X_CLINIC_ID"] = "sunrise-clinic"

    response = api_client.get("/api/v1/appointments/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_service_token_cannot_select_another_clinic(
    api_client, service_token, clinic, other_clinic
):
    """The token *is* the tenant binding: the header cannot override it."""
    raw, _row = service_token
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    api_client.defaults["HTTP_X_CLINIC_ID"] = str(other_clinic.id)

    response = api_client.get("/api/v1/tools/")

    assert response.status_code == 200
    # The resolved tenant is the token's clinic, not the header's.
    assert response.data["clinic_id"] == str(clinic.id)


@pytest.mark.django_db
def test_an_unauthenticated_request_is_refused(api_client, clinic):
    response = api_client.get("/api/v1/appointments/")

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_the_patient_list_is_scoped_to_the_clinic(
    auth_client, clinic, other_clinic, patient, other_patient
):
    response = auth_client.get("/api/v1/patients/")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == str(patient.id)


@pytest.mark.django_db
def test_cannot_book_a_patient_from_another_clinic(
    auth_client, clinic, other_clinic, doctor, other_patient, slot_time
):
    """Booking somebody else's patient is refused at the API boundary."""
    response = auth_client.post(
        "/api/v1/appointments/",
        {
            "doctor": str(doctor.id),
            "patient": str(other_patient.id),
            "start_at": slot_time.isoformat(),
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "patient_not_found"


@pytest.mark.django_db
def test_availability_slots_are_scoped_to_the_clinic(
    auth_client, clinic, other_clinic, doctor, next_monday
):
    response = auth_client.get(f"/api/v1/availability/slots/?date={next_monday.isoformat()}")

    assert response.status_code == 200
    assert response.data["count"] == 14
    assert all(s["doctor_id"] == str(doctor.id) for s in response.data["results"])


@pytest.mark.django_db
def test_the_dashboard_summary_is_scoped_to_the_clinic(
    auth_client, clinic, other_clinic, doctor, patient, other_appointment
):
    response = auth_client.get("/api/v1/dashboard/summary/")

    assert response.status_code == 200
    body = response.data
    # The other tenant's appointment is not counted.
    assert body.get("appointments", {}).get("upcoming", 0) == 0
