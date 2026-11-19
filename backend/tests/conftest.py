"""Shared fixtures.

Two things make these fixtures unusual, and both are deliberate:

1. **Row Level Security is on.** Tenant rows are invisible unless the
   database session has been scoped with ``app.current_clinic_id``. Every
   fixture that touches a tenant table therefore runs inside ``rls_scope``.
   This is not ceremony -- it is what makes the tests prove that the
   application cannot accidentally read across tenants.

2. **Tenants are built explicitly.** There is no "default clinic" fixture
   that everything shares, because a shared fixture would hide exactly the
   cross-tenant bugs the suite exists to catch.
"""
from __future__ import annotations

import uuid
from datetime import time, timedelta

import pytest
from django.utils import timezone


@pytest.fixture(autouse=True)
def _inline_message_delivery(settings):
    """Keep outbound delivery deterministic in tests.

    Production queues provider calls to Celery. Running them inline here makes
    the whole suite assert on real provider results without a worker, and keeps
    the tests independent of ``transaction.on_commit`` timing.
    """
    settings.MESSAGES_ASYNC = False


# ---------------------------------------------------------------------------
# Clinics
# ---------------------------------------------------------------------------
def _make_clinic(slug_prefix: str):
    from apps.core.constants import ClinicStatus
    from apps.tenancy.models import Clinic, ClinicSettings

    clinic = Clinic.objects.create(
        name=f"{slug_prefix} Clinic",
        slug=f"{slug_prefix}-{uuid.uuid4().hex[:8]}",
        timezone="Asia/Kolkata",
        status=ClinicStatus.ACTIVE,
        onboarded_at=timezone.now(),
    )
    ClinicSettings.objects.create(clinic=clinic)
    return clinic


@pytest.fixture
def clinic(db):
    """The clinic under test."""
    return _make_clinic("alpha")


@pytest.fixture
def other_clinic(db):
    """A second, unrelated tenant."""
    return _make_clinic("beta")


@pytest.fixture
def scoped(clinic):
    """Scope the database session to ``clinic`` for the whole test."""
    from apps.core.rls import rls_scope

    with rls_scope(str(clinic.id)):
        yield clinic


@pytest.fixture
def scoped_other(other_clinic):
    """Scope the database session to ``other_clinic`` for the whole test."""
    from apps.core.rls import rls_scope

    with rls_scope(str(other_clinic.id)):
        yield other_clinic


@pytest.fixture
def as_clinic():
    """A context manager that scopes the session to a clinic.

    Every request clears the Row Level Security scope when it finishes --
    that is how a pooled connection is kept from carrying one tenant's
    scope into the next request. A test that reads tenant rows back
    *after* a request therefore has to re-apply the scope.
    """
    import contextlib

    from apps.core.rls import rls_scope

    @contextlib.contextmanager
    def _scope(clinic):
        with rls_scope(str(clinic.id)):
            yield clinic

    return _scope


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
@pytest.fixture
def staff_user(db):
    from apps.accounts.models import User

    return User.objects.create_user(
        username="staff@example.test",
        email="staff@example.test",
        password="test-password-123",
        first_name="Sita",
        last_name="Rao",
    )


@pytest.fixture
def admin_user(db):
    from apps.accounts.models import User

    return User.objects.create_user(
        username="admin@example.test",
        email="admin@example.test",
        password="test-password-123",
    )


@pytest.fixture
def membership(clinic, staff_user):
    from apps.accounts.models import ClinicMembership

    return ClinicMembership.objects.create(
        clinic=clinic, user=staff_user, role="receptionist", status="active"
    )


@pytest.fixture
def admin_membership(clinic, admin_user):
    from apps.accounts.models import ClinicMembership

    return ClinicMembership.objects.create(
        clinic=clinic, user=admin_user, role="clinic_admin", status="active"
    )


@pytest.fixture
def doctor(scoped):
    """A doctor working Monday-Saturday, 09:00-13:00 and 16:00-19:00."""
    from apps.doctors.models import Doctor, DoctorSchedule

    doc = Doctor.objects.create(
        clinic=scoped,
        name="Anita Rao",
        slug="anita-rao",
        specialization="General Medicine",
        phone="+919000000001",
        languages=["hi-IN", "en-IN"],
        sort_order=1,
    )
    for weekday in range(6):  # Monday..Saturday
        DoctorSchedule.objects.create(
            clinic=scoped, doctor=doc, weekday=weekday, start_time=time(9, 0), end_time=time(13, 0)
        )
        DoctorSchedule.objects.create(
            clinic=scoped, doctor=doc, weekday=weekday, start_time=time(16, 0), end_time=time(19, 0)
        )
    return doc


@pytest.fixture
def second_doctor(scoped):
    from apps.doctors.models import Doctor, DoctorSchedule

    doc = Doctor.objects.create(
        clinic=scoped,
        name="Vikram Shetty",
        slug="vikram-shetty",
        specialization="Cardiology",
        phone="+919000000002",
        sort_order=2,
    )
    for weekday in range(6):
        DoctorSchedule.objects.create(
            clinic=scoped, doctor=doc, weekday=weekday, start_time=time(9, 0), end_time=time(13, 0)
        )
    return doc


@pytest.fixture
def patient(scoped):
    from apps.appointments.models import Patient

    return Patient.objects.create(
        clinic=scoped,
        name="Ravi Kumar",
        phone="+919000100001",
        preferred_language="hi-IN",
        communication_preferences={"opt_out_sms": False, "opt_out_whatsapp": False},
    )


@pytest.fixture
def other_patient(other_clinic):
    """A patient of the *other* tenant.

    The row is written inside the other tenant's scope: with RLS on, a
    write carrying a foreign ``clinic_id`` is rejected by the database.
    """
    from apps.appointments.models import Patient
    from apps.core.rls import rls_scope

    with rls_scope(str(other_clinic.id)):
        return Patient.objects.create(
            clinic=other_clinic, name="Other Patient", phone="+919000100002"
        )


@pytest.fixture
def other_appointment(other_clinic, slot_time):
    """A booked appointment that belongs to the *other* tenant.

    The doctor gets a real rota so that the booking is legitimate -- the
    point of the test is the tenant boundary, not the availability rules.
    """
    from apps.appointments.models import Patient
    from apps.appointments.services.booking import BookingService
    from apps.core.rls import rls_scope
    from apps.doctors.models import Doctor, DoctorSchedule

    with rls_scope(str(other_clinic.id)):
        hidden_doctor = Doctor.objects.create(
            clinic=other_clinic,
            name="Hidden Doctor",
            slug="hidden-doctor",
            phone="+919000900001",
        )
        for weekday in range(6):
            DoctorSchedule.objects.create(
                clinic=other_clinic,
                doctor=hidden_doctor,
                weekday=weekday,
                start_time=time(9, 0),
                end_time=time(13, 0),
            )
        hidden_patient = Patient.objects.create(
            clinic=other_clinic, name="Hidden Patient", phone="+919000900002"
        )
        appointment = BookingService.book(
            clinic=other_clinic,
            doctor=hidden_doctor,
            patient=hidden_patient,
            start_at=slot_time,
        )
    return appointment


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _next_weekday(weekday: int, days_ahead: int = 7) -> object:
    """The next date (at least ``days_ahead`` away) that falls on ``weekday``."""
    day = timezone.localdate() + timedelta(days=days_ahead)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day


@pytest.fixture
def next_monday():
    """A Monday comfortably inside the 30-day booking horizon."""
    return _next_weekday(0)


@pytest.fixture
def slot_time(next_monday):
    """09:00 IST on the next Monday, as an aware UTC datetime."""
    from apps.core.timeutils import combine_local, get_zone

    return combine_local(next_monday, time(9, 0), get_zone("Asia/Kolkata"))


# ---------------------------------------------------------------------------
# API clients
# ---------------------------------------------------------------------------
@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def auth_client(api_client, staff_user, membership, clinic):
    """An API client authenticated as the receptionist of ``clinic``."""
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(staff_user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    api_client.defaults["HTTP_X_CLINIC_ID"] = str(clinic.id)
    return api_client


@pytest.fixture
def admin_client(api_client, admin_user, admin_membership, clinic):
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(admin_user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    api_client.defaults["HTTP_X_CLINIC_ID"] = str(clinic.id)
    return api_client


@pytest.fixture
def service_token(clinic):
    """A raw service token for ``clinic`` plus its stored row."""
    from apps.accounts.models import ClinicServiceToken
    from apps.core.authentication import generate_token, hash_token

    raw = generate_token()
    row = ClinicServiceToken.objects.create(
        clinic=clinic,
        name="voice-agent",
        token_hash=hash_token(raw),
        scopes=["tools:invoke"],
        provider_type="sarvam",
    )
    return raw, row


@pytest.fixture
def voice_number(scoped):
    """A voice number that routes inbound calls to ``clinic``."""
    from apps.tenancy.models import ClinicChannelNumber

    return ClinicChannelNumber.objects.create(
        clinic=scoped,
        channel="voice",
        external_number_id="+919000000001",
        display_number="+919000000001",
        routing_status="active",
    )


@pytest.fixture
def other_voice_number(other_clinic):
    """A voice number that routes to the *other* tenant."""
    from apps.tenancy.models import ClinicChannelNumber

    return ClinicChannelNumber.objects.create(
        clinic=other_clinic,
        channel="voice",
        external_number_id="+919000000009",
        display_number="+919000000009",
        routing_status="active",
    )


@pytest.fixture
def whatsapp_number(scoped):
    """The WhatsApp business number (Meta phone number id) for ``clinic``."""
    from apps.tenancy.models import ClinicChannelNumber

    return ClinicChannelNumber.objects.create(
        clinic=scoped,
        channel="whatsapp",
        external_number_id="phone-1",
        display_number="+919000000002",
        routing_status="active",
    )


@pytest.fixture
def token_client(api_client, service_token):
    """An API client authenticated with the clinic's service token."""
    raw, _row = service_token
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return api_client
