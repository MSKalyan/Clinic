"""Row Level Security: the database-level half of tenant isolation (PRD 3.2).

These tests do not go through the API. They talk to the database directly to
prove that the *database* refuses to show a tenant another tenant's rows --
so even a missing ``filter(clinic=...)`` in the application is a bug that
fails closed instead of a data leak.
"""
from __future__ import annotations

import pytest

from apps.core.rls import clear_rls_clinic, get_rls_clinic, rls_scope


@pytest.mark.django_db
def test_tenant_rows_are_invisible_without_a_scope(clinic, doctor, patient):
    """With no tenant established, the tables are empty -- not 'everything'."""
    from apps.appointments.models import Patient
    from apps.doctors.models import Doctor

    clear_rls_clinic()

    assert Doctor.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.django_db
def test_scope_exposes_only_the_own_tenant(clinic, other_clinic, doctor, patient):
    from apps.appointments.models import Patient
    from apps.doctors.models import Doctor

    with rls_scope(str(clinic.id)):
        assert Doctor.objects.count() == 1
        assert Patient.objects.count() == 1
        assert {str(d.clinic_id) for d in Doctor.objects.all()} == {str(clinic.id)}

    with rls_scope(str(other_clinic.id)):
        assert Doctor.objects.count() == 0
        assert Patient.objects.count() == 0


@pytest.mark.django_db
def test_writes_to_another_tenant_are_rejected(clinic, other_clinic, scoped):
    """A row written under the wrong scope does not land."""
    from apps.appointments.models import Patient

    with rls_scope(str(other_clinic.id)):
        Patient.objects.create(
            clinic=other_clinic, name="Wrong Tenant", phone="+919000199999"
        )

    with rls_scope(str(clinic.id)):
        assert Patient.objects.filter(phone="+919000199999").count() == 0

    with rls_scope(str(other_clinic.id)):
        assert Patient.objects.filter(phone="+919000199999").count() == 1


@pytest.mark.django_db
def test_scope_is_restored_after_a_nested_block(clinic, other_clinic):
    with rls_scope(str(clinic.id)):
        assert get_rls_clinic() == str(clinic.id)
        with rls_scope(str(other_clinic.id)):
            assert get_rls_clinic() == str(other_clinic.id)
        assert get_rls_clinic() == str(clinic.id)
    assert get_rls_clinic() == ""


@pytest.mark.django_db
def test_background_sweep_iterates_one_tenant_at_a_time(clinic, other_clinic):
    """``iter_clinic_scopes`` never runs unscoped."""
    from apps.core.rls import iter_clinic_scopes

    seen = []
    for tenant, scope in iter_clinic_scopes(include_offboarded=True):
        assert scope == str(tenant.id)
        assert get_rls_clinic() == scope
        seen.append(scope)

    assert str(clinic.id) in seen
    assert str(other_clinic.id) in seen


@pytest.mark.django_db
def test_audit_log_is_immutable(clinic, scoped):
    from django.db import connection

    from apps.core.audit import record_audit
    from apps.core.constants import AuditAction
    from apps.core.models import AuditLog

    record_audit(
        action=AuditAction.BOOK,
        resource_type="appointment",
        resource_id="abc",
        clinic_id=clinic.id,
    )
    entry = AuditLog.objects.first()
    assert entry is not None

    with pytest.raises(PermissionError):
        entry.save()

    with pytest.raises(PermissionError):
        entry.delete()
