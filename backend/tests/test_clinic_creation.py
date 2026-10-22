"""Creating a clinic is the one flow that creates its own tenant.

Every other request already has a tenant: a staff member's membership or a
service token names the clinic before anything is read or written. Creating
a clinic is different -- the clinic does not exist yet, so the request
arrives with no tenant scope at all.

That is where the row-level security policy bites: the audit row and the
admin membership both belong to the *new* clinic, and the policy only
accepts a write whose ``clinic_id`` matches the session scope. The
endpoint therefore has to scope the session to the clinic it just created
before writing those rows.
"""
from __future__ import annotations

import uuid

import pytest


@pytest.fixture
def new_admin(db):
    """A user with no clinic membership at all."""
    from apps.accounts.models import User

    return User.objects.create_user(
        username="founder@example.test",
        email="founder@example.test",
        password="test-password-123",
        first_name="Rhea",
        last_name="Kapoor",
    )


def _fake_request(user):
    """A minimal request object good enough for ``perform_create``."""
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    django_request = factory.post("/api/v1/clinics/")
    django_request.user = user
    request = Request(django_request)
    request.user = user
    return request


def _create_clinic(user, name):
    """Run the view's create path and return the saved clinic."""
    from apps.api.v1.serializers import ClinicSerializer
    from apps.api.v1.views.clinics import ClinicViewSet

    view = ClinicViewSet()
    view.request = _fake_request(user)
    view.format_kwarg = None

    serializer = ClinicSerializer(
        data={"name": name, "slug": f"{name.split()[0].lower()}-{uuid.uuid4().hex[:8]}"}
    )
    assert serializer.is_valid(), serializer.errors
    view.perform_create(serializer)
    return serializer.instance


def test_creating_a_clinic_gives_the_creator_admin_rights(new_admin):
    """The creator becomes a clinic admin of the clinic they just made."""
    from apps.accounts.models import ClinicMembership

    # The caller's session has no tenant scope: they belong to nothing yet.
    from apps.core.rls import get_rls_clinic

    assert get_rls_clinic() == ""

    clinic = _create_clinic(new_admin, "Harbour Clinic")

    membership = ClinicMembership.objects.filter(
        clinic=clinic, user=new_admin, role="clinic_admin", status="active"
    ).first()
    assert membership is not None, "the creator was not made a clinic admin"


def test_the_audit_trail_records_the_new_clinic(new_admin):
    """The clinic creation is audited against the new clinic."""
    from apps.core.models import AuditLog
    from apps.core.rls import rls_scope

    clinic = _create_clinic(new_admin, "Lakeside Clinic")

    # The audit row is only visible inside the clinic's own scope, which is
    # exactly how a tenant-scoped audit trail is supposed to behave.
    with rls_scope(str(clinic.id)):
        entry = AuditLog.objects.filter(
            clinic_id=clinic.id, resource_type="clinic"
        ).first()
    assert entry is not None, "the clinic creation was not audited"


def test_audit_failures_do_not_break_the_request(new_admin, monkeypatch):
    """A failed audit write must not roll back the clinic."""
    from apps.core.models import AuditLog

    def explode(*_args, **_kwargs):
        raise RuntimeError("the audit table is on fire")

    monkeypatch.setattr(AuditLog.objects, "create", explode)

    # Must not raise.
    clinic = _create_clinic(new_admin, "Hillcrest Clinic")
    assert clinic is not None
    assert clinic.name == "Hillcrest Clinic"
