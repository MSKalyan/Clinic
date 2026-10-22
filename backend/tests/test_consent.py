"""Consent, opt-out and notification idempotency (PRD 5.5 / 12.3).

Consent is enforced at the moment a message is *sent*, not when it is
scheduled, so a patient who opts out after a reminder was queued still
does not receive it. An explicit opt-out always beats a recorded consent.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def stub_messaging(monkeypatch):
    """Replace the outbound provider with a recording stub."""
    import apps.integrations.providers as providers

    sent: list[dict] = []

    class StubProvider:
        provider_type = "whatsapp"

        def send_message(self, *, clinic, recipient_phone, template_id, body="", appointment=None, payload=None):
            sent.append(
                {
                    "clinic_id": str(clinic.id),
                    "recipient_phone": recipient_phone,
                    "template_id": template_id,
                    "body": body,
                }
            )
            return f"stub-message-{len(sent)}"

    monkeypatch.setattr(providers, "get_messaging_provider", lambda clinic, channel: StubProvider())
    return sent


@pytest.fixture
def consented_patient(scoped, patient):
    from apps.appointments.models import PatientConsent

    PatientConsent.objects.create(
        clinic=scoped,
        patient=patient,
        purpose="reminders",
        channel="whatsapp",
        consent_status="granted",
    )
    return patient


# ---------------------------------------------------------------------------
# Opt-out
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_patient_who_opted_out_is_not_contacted(scoped, patient):
    from apps.conversations.services.notifications import NotificationService
    from apps.core.exceptions import OptedOut

    patient.communication_preferences = {"opt_out_whatsapp": True}
    patient.save(update_fields=["communication_preferences"])

    with pytest.raises(OptedOut):
        NotificationService.send(
            clinic=scoped,
            patient=patient,
            channel="whatsapp",
            template_id="appointment_reminder",
            body="Your appointment is tomorrow.",
            purpose="reminders",
        )


@pytest.mark.django_db
def test_an_opt_out_is_recorded_even_when_consent_was_granted(scoped, patient):
    """An explicit opt-out wins over an earlier consent."""
    from apps.appointments.models import PatientConsent
    from apps.conversations.services.notifications import NotificationService
    from apps.core.exceptions import OptedOut

    PatientConsent.objects.create(
        clinic=scoped,
        patient=patient,
        purpose="reminders",
        channel="whatsapp",
        consent_status="granted",
    )
    patient.communication_preferences = {"opt_out_whatsapp": True}
    patient.save(update_fields=["communication_preferences"])

    with pytest.raises(OptedOut):
        NotificationService.send(
            clinic=scoped,
            patient=patient,
            channel="whatsapp",
            template_id="appointment_reminder",
            purpose="reminders",
        )


@pytest.mark.django_db
def test_withdrawn_consent_blocks_the_message(scoped, patient):
    from apps.appointments.models import PatientConsent
    from apps.conversations.services.notifications import NotificationService
    from apps.core.exceptions import OptedOut

    PatientConsent.objects.create(
        clinic=scoped,
        patient=patient,
        purpose="reminders",
        channel="whatsapp",
        consent_status="withdrawn",
    )

    with pytest.raises(OptedOut):
        NotificationService.send(
            clinic=scoped,
            patient=patient,
            channel="whatsapp",
            template_id="appointment_reminder",
            purpose="reminders",
        )


@pytest.mark.django_db
def test_marketing_without_consent_is_refused(scoped, patient):
    """Transactional messages are necessary; marketing is not."""
    from apps.conversations.services.notifications import NotificationService
    from apps.core.exceptions import ConsentRequired

    with pytest.raises(ConsentRequired):
        NotificationService.send(
            clinic=scoped,
            patient=patient,
            channel="whatsapp",
            template_id="campaign",
            body="We have a special offer.",
            purpose="marketing",
        )


@pytest.mark.django_db
def test_a_transactional_message_needs_no_marketing_consent(
    scoped, stub_messaging, patient
):
    from apps.conversations.services.notifications import NotificationService

    log = NotificationService.send(
        clinic=scoped,
        patient=patient,
        channel="whatsapp",
        template_id="appointment_confirmation",
        body="You are booked.",
        purpose="appointment_transactional",
    )

    assert log.delivery_status == "sent"
    assert len(stub_messaging) == 1
    assert stub_messaging[0]["recipient_phone"] == patient.phone


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_the_same_notification_is_not_sent_twice(scoped, stub_messaging, patient):
    from apps.conversations.services.notifications import NotificationService

    first = NotificationService.send(
        clinic=scoped,
        patient=patient,
        channel="whatsapp",
        template_id="appointment_reminder",
        purpose="reminders",
        idempotency_key="reminder:abc",
    )
    second = NotificationService.send(
        clinic=scoped,
        patient=patient,
        channel="whatsapp",
        template_id="appointment_reminder",
        purpose="reminders",
        idempotency_key="reminder:abc",
    )

    assert first.id == second.id
    assert len(stub_messaging) == 1


@pytest.mark.django_db
def test_an_opted_out_patient_leaves_no_notification_log(scoped, patient):
    """A refused message must not even be recorded as attempted."""
    from apps.conversations.models import NotificationLog
    from apps.conversations.services.notifications import NotificationService
    from apps.core.exceptions import OptedOut

    patient.communication_preferences = {"opt_out_whatsapp": True}
    patient.save(update_fields=["communication_preferences"])

    with pytest.raises(OptedOut):
        NotificationService.send(
            clinic=scoped,
            patient=patient,
            channel="whatsapp",
            template_id="appointment_reminder",
            purpose="reminders",
        )

    assert NotificationLog.objects.filter(clinic=scoped).count() == 0


@pytest.mark.django_db
def test_the_audit_trail_does_not_store_patient_content(scoped, patient):
    """Audit rows carry identifiers, never the content of a message."""
    from apps.core.audit import record_audit
    from apps.core.models import AuditLog

    record_audit(
        action="book",
        resource_type="appointment",
        resource_id="11111111-1111-1111-1111-111111111111",
        clinic_id=scoped.id,
        actor=None,
        metadata={
            "reference": "APT123",
            "phone": "+919000100001",
            "message": "My name is Ravi and I have chest pain",
        },
    )

    entry = AuditLog.objects.filter(clinic_id=scoped.id).get()
    assert entry.metadata.get("reference") == "APT123"
    assert "phone" not in entry.metadata
    assert "message" not in entry.metadata
