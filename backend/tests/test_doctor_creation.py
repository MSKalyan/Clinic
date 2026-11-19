"""Adding a doctor through the dashboard creates a bookable, uniquely-slugged row."""
from __future__ import annotations

import pytest
from django.test import override_settings

WAIT_SETTINGS = {"MESSAGES_ASYNC": False}


@pytest.mark.django_db
@override_settings(**WAIT_SETTINGS)
def test_admin_can_add_multiple_doctors_with_unique_slugs(admin_client, clinic):
    response = admin_client.post(
        "/api/v1/doctors/",
        {
            "name": "Ada Lovelace",
            "specialization": "General Medicine",
            "phone": "+919000000010",
            "languages": ["en-IN"],
            "sort_order": 1,
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    first = response.json()
    assert first["slug"] == "ada-lovelace"

    # A second doctor with the same name must still get a unique slug.
    response = admin_client.post(
        "/api/v1/doctors/",
        {
            "name": "Ada Lovelace",
            "specialization": "Cardiology",
            "phone": "+919000000011",
            "languages": ["en-IN"],
            "sort_order": 2,
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    second = response.json()
    assert second["slug"] == "ada-lovelace-2"
    assert second["id"] != first["id"]

    # Both appear in the roster.
    listing = admin_client.get("/api/v1/doctors/")
    assert listing.status_code == 200
    ids = {row["id"] for row in listing.json()["results"]}
    assert {first["id"], second["id"]} <= ids


@pytest.mark.django_db
@override_settings(**WAIT_SETTINGS)
def test_editing_doctor_name_updates_slug(admin_client, clinic, doctor):
    response = admin_client.patch(
        f"/api/v1/doctors/{doctor.id}/",
        {"name": "Anita Sharma"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["slug"] == "anita-sharma"


@pytest.mark.django_db
@override_settings(**WAIT_SETTINGS)
def test_new_doctor_appears_in_whatsapp_booking_flow(admin_client, clinic, next_monday):
    created = admin_client.post(
        "/api/v1/doctors/",
        {
            "name": "Grace Hopper",
            "specialization": "General Medicine",
            "phone": "+919000000012",
            "languages": ["en-IN"],
            "sort_order": 3,
            "is_active": True,
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    doctor_id = created.json()["id"]

    from apps.core.rls import rls_scope
    from apps.doctors.models import Doctor
    from apps.integrations.services.bot_flow import _info, _slots_for

    with rls_scope(str(clinic.id)):
        new_doctor = Doctor.objects.get(pk=doctor_id)
        # Patients only use WhatsApp, so a new doctor must appear in the
        # dynamic assistant message and be bookable straight away.
        message = _info(clinic)
        assert new_doctor.name in message
        assert new_doctor.specialization in message
        assert _slots_for(clinic, new_doctor, next_monday)


@pytest.mark.django_db
def test_new_doctor_gets_the_clinic_operating_hours_as_a_schedule(admin_client, clinic):
    from apps.doctors.models import Doctor, DoctorSchedule

    created = admin_client.post(
        "/api/v1/doctors/",
        {
            "name": "Marie Curie",
            "specialization": "General Medicine",
            "phone": "+919000000013",
            "is_active": True,
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    doctor = Doctor.objects.get(pk=created.json()["id"])

    schedule = DoctorSchedule.objects.filter(doctor=doctor)
    assert schedule.count() == 6  # Mon-Sat; Sunday is closed by default.
    assert set(schedule.values_list("weekday", flat=True)) == {0, 1, 2, 3, 4, 5}

    # Calling the seed again never duplicates or overwrites the schedule.
    from apps.doctors.services.schedule import seed_default_schedule

    assert seed_default_schedule(doctor) == 0
    assert DoctorSchedule.objects.filter(doctor=doctor).count() == 6
