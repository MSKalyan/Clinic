"""Per-clinic provider credentials.

The security properties this module is responsible for:

* a secret value is **never** returned by the API;
* a secret value is **never** stored in plaintext;
* a clinic can only see and change **its own** keys;
* a clinic admin can only manage keys that belong to a clinic;
* the audit trail records **which** key was set, never the value.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def admin(api_client, admin_user, admin_membership, clinic):
    """An API client authenticated as the clinic admin of ``clinic``."""
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(admin_user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    api_client.defaults["HTTP_X_CLINIC_ID"] = str(clinic.id)
    return api_client


@pytest.fixture
def receptionist(api_client, staff_user, membership, clinic):
    """An API client authenticated as the receptionist of ``clinic``."""
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(staff_user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    api_client.defaults["HTTP_X_CLINIC_ID"] = str(clinic.id)
    return api_client


# ---------------------------------------------------------------------------
# Reading the status
# ---------------------------------------------------------------------------
def test_the_status_lists_every_key(admin, clinic):
    response = admin.get(f"/api/v1/clinics/{clinic.id}/configuration/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["keys"]
    assert payload["summary"]["total"] == len(payload["keys"])
    assert payload["groups"]


def test_the_status_has_a_set_or_not_column(admin, clinic):
    """Every key reports one of the three states."""
    response = admin.get(f"/api/v1/clinics/{clinic.id}/configuration/")
    payload = response.json()

    for item in payload["keys"]:
        assert item["status"] in {"set", "platform", "missing"}
        assert item["is_set"] == (item["status"] in {"set", "platform"})


def test_a_receptionist_cannot_see_the_configuration(receptionist, clinic):
    """Only a clinic administrator may see the provider keys."""
    response = receptionist.get(f"/api/v1/clinics/{clinic.id}/configuration/")

    assert response.status_code == 403


def test_the_status_never_contains_a_secret_value(admin, clinic):
    """The payload has no field that could hold a secret."""
    response = admin.get(f"/api/v1/clinics/{clinic.id}/configuration/")
    raw = response.content.decode()

    for item in response.json()["keys"]:
        assert "value" not in item
    assert "sk_live" not in raw


# ---------------------------------------------------------------------------
# Writing a value
# ---------------------------------------------------------------------------
def test_an_admin_can_set_a_key(admin, clinic):
    response = admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/",
        {"value": "sk_test_12345"},
        format="json",
    )

    assert response.status_code == 200
    item = response.json()["key"]
    assert item["status"] == "set"
    assert item["source"] == "clinic"


def test_the_value_is_stored_encrypted(admin, clinic):
    """The column holds ciphertext, not the value."""
    from apps.core.rls import rls_scope
    from apps.tenancy.models import ClinicSecret

    admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/",
        {"value": "sk_test_plaintext_marker"},
        format="json",
    )

    with rls_scope(str(clinic.id)):
        row = ClinicSecret.objects.get(clinic=clinic, key="sarvam.api_key")

    assert "sk_test_plaintext_marker" not in row.ciphertext
    assert row.ciphertext.startswith("gAAAA")  # Fernet ciphertext


def test_the_value_round_trips(admin, clinic):
    """The provider can still read the value back."""
    from apps.core.secrets import get_clinic_value, resolve

    admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/",
        {"value": "sk_test_roundtrip"},
        format="json",
    )

    assert get_clinic_value(clinic, "sarvam.api_key") == "sk_test_roundtrip"
    value, source = resolve(clinic, "sarvam.api_key")
    assert value == "sk_test_roundtrip"
    assert source == "clinic"


def test_the_response_never_echoes_the_value(admin, clinic):
    admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/",
        {"value": "sk_test_never_echoed"},
        format="json",
    )

    response = admin.get(f"/api/v1/clinics/{clinic.id}/configuration/")
    assert "sk_test_never_echoed" not in response.content.decode()


def test_a_receptionist_cannot_set_a_key(receptionist, clinic):
    response = receptionist.put(
        f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/",
        {"value": "sk_test_not_allowed"},
        format="json",
    )

    assert response.status_code == 403


def test_a_platform_scoped_key_cannot_be_set_by_a_clinic(admin, clinic):
    """The platform's own settings are not the clinic's to change."""
    response = admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/platform.django_secret_key/",
        {"value": "hijacked"},
        format="json",
    )

    assert response.status_code == 403
    assert "platform setting" in response.json()["error"]["message"].lower()


def test_an_unknown_key_is_rejected(admin, clinic):
    response = admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/not.a.real.key/",
        {"value": "x"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_key"


def test_an_empty_value_is_rejected(admin, clinic):
    response = admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/",
        {"value": "   "},
        format="json",
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Removing a value
# ---------------------------------------------------------------------------
def test_an_admin_can_remove_a_key(admin, clinic):
    admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/",
        {"value": "sk_test_to_remove"},
        format="json",
    )

    response = admin.delete(f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/")

    assert response.status_code == 200
    assert response.json()["removed"] is True
    assert response.json()["key"]["status"] != "set"


def test_removing_a_key_that_was_never_set_is_harmless(admin, clinic):
    response = admin.delete(f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/")

    assert response.status_code == 200
    assert response.json()["removed"] is False


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
def test_one_clinic_cannot_set_another_clinics_key(admin, other_clinic):
    """The header selects the clinic; the body cannot."""
    response = admin.put(
        f"/api/v1/clinics/{other_clinic.id}/configuration/sarvam.api_key/",
        {"value": "sk_test_cross_tenant"},
        format="json",
    )

    # Either the other clinic is not visible to this admin (404), or the
    # write is refused. What must not happen is a successful write.
    assert response.status_code in (403, 404)


def test_the_audit_trail_records_the_key_but_not_the_value(admin, clinic):
    """The audit log says which key was set, never what it was."""
    from apps.core.models import AuditLog
    from apps.core.rls import rls_scope

    admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/",
        {"value": "sk_test_audited_value"},
        format="json",
    )

    # The queryset has to be materialised *inside* the scope. A lazy
    # queryset would be evaluated after the scope was restored, and the
    # row-level security policy would then hide every row.
    with rls_scope(str(clinic.id)):
        entries = list(
            AuditLog.objects.filter(
                clinic_id=clinic.id, resource_type="clinic_secret"
            )
        )

    assert entries, "no audit entry was written for the key change"
    for entry in entries:
        assert "sk_test_audited_value" not in str(entry.metadata)


# ---------------------------------------------------------------------------
# The key registry
# ---------------------------------------------------------------------------
def test_every_key_has_a_label_and_a_purpose():
    from apps.core.secrets import KEY_SPECS

    for spec in KEY_SPECS:
        assert spec.key
        assert spec.label
        assert spec.purpose
        assert spec.env_var
        assert spec.scope in {"clinic", "platform"}


def test_the_keys_are_unique():
    from apps.core.secrets import KEY_SPECS

    keys = [spec.key for spec in KEY_SPECS]
    assert len(keys) == len(set(keys))


def test_a_clinics_key_wins_over_the_platform_default(admin, clinic, settings):
    """A clinic that brings its own account is not overridden."""
    from apps.core.secrets import resolve

    settings.SARVAM_API_KEY = "platform-shared-key"

    assert resolve(clinic, "sarvam.api_key") == ("platform-shared-key", "platform")

    admin.put(
        f"/api/v1/clinics/{clinic.id}/configuration/sarvam.api_key/",
        {"value": "clinic-own-key"},
        format="json",
    )

    assert resolve(clinic, "sarvam.api_key") == ("clinic-own-key", "clinic")
