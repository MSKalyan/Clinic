"""Provider webhook handling (PRD 10.6).

Four properties matter here, and each of them is a security property:

1. **Authenticity** -- a webhook that does not carry the provider's
   credential is rejected *before* anything is read.
2. **Idempotency** -- the same provider event delivered twice is applied
   once.
3. **Routing** -- the clinic is derived from the number the patient
   dialled, never from the payload body.
4. **Containment** -- an event for one tenant never touches another
   tenant's rows.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from django.test import override_settings

WEBHOOK_SECRET = "s3cr3t-voice-hook"


def _voice_payload(**overrides) -> dict:
    payload = {
        "interaction_id": "int-abc-123",
        "user_phone_number": "+919000100001",
        "agent_phone_number": "+919000000001",
        "duration": 125,
        "start_datetime": "2026-10-20T09:00:00Z",
        "end_datetime": "2026-10-20T09:02:05Z",
        "final_agent_variables": {"call_outcome": "resolved"},
        "interaction_transcript": [
            {"role": "agent", "en_text": "Hello, Sunita Clinic."},
            {"role": "user", "en_text": "I want a doctor appointment."},
        ],
    }
    payload.update(overrides)
    return payload


def _post_voice(client, payload, *, secret: str = WEBHOOK_SECRET):
    return client.post(
        f"/api/v1/webhooks/voice/sarvam/{secret}/",
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.fixture(autouse=True)
def _configured_secret():
    with override_settings(SARVAM_WEBHOOK_SECRET=WEBHOOK_SECRET):
        yield


@pytest.mark.django_db
def test_a_voice_webhook_without_the_secret_is_rejected(api_client, clinic, voice_number):
    """No credential, no data."""
    response = _post_voice(api_client, _voice_payload(), secret="not-the-secret")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_signature"


@pytest.mark.django_db
def test_a_voice_webhook_without_any_secret_is_rejected(api_client, clinic, voice_number):
    response = api_client.post(
        "/api/v1/webhooks/voice/sarvam/",
        data=json.dumps(_voice_payload()),
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_rejected_webhook_records_nothing(as_clinic, api_client, clinic, voice_number):
    from apps.conversations.models import CallLog

    response = _post_voice(api_client, _voice_payload(), secret="wrong")

    assert response.status_code == 403
    with as_clinic(clinic):
        assert CallLog.objects.filter(clinic=clinic).count() == 0


@pytest.mark.django_db
def test_a_valid_voice_webhook_is_accepted(as_clinic, api_client, clinic, voice_number):
    from apps.conversations.models import CallLog

    response = _post_voice(api_client, _voice_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["processed"] == 1
    assert body["duplicates"] == 0

    with as_clinic(clinic):
        call = CallLog.objects.filter(clinic=clinic).get()
    assert call.provider_call_id == "int-abc-123"
    assert call.duration_seconds == 125
    assert call.outcome == "resolved"


@pytest.mark.django_db
def test_the_secret_can_travel_in_the_header_instead_of_the_url(
    as_clinic, api_client, clinic, voice_number
):
    from apps.conversations.models import CallLog

    response = api_client.post(
        "/api/v1/webhooks/voice/sarvam/",
        data=json.dumps(_voice_payload()),
        content_type="application/json",
        HTTP_X_WEBHOOK_SECRET=WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    with as_clinic(clinic):
        assert CallLog.objects.filter(clinic=clinic).count() == 1


@pytest.mark.django_db
def test_a_duplicate_delivery_is_applied_once(as_clinic, api_client, clinic, voice_number):
    """Providers retry. A retry must not create a second call log."""
    from apps.conversations.models import CallLog
    from apps.integrations.models import ProviderEvent

    first = _post_voice(api_client, _voice_payload())
    second = _post_voice(api_client, _voice_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicates"] == 1
    assert second.json()["accepted"] == 0

    with as_clinic(clinic):
        assert CallLog.objects.filter(clinic=clinic).count() == 1
        assert ProviderEvent.objects.filter(clinic=clinic).count() == 1


@pytest.mark.django_db
def test_the_clinic_comes_from_the_dialled_number(
    as_clinic, api_client, clinic, other_clinic, voice_number, other_voice_number
):
    """The body may claim any clinic it likes; the number decides."""
    from apps.conversations.models import CallLog

    response = _post_voice(
        api_client,
        _voice_payload(
            interaction_id="int-routing",
            agent_phone_number="+919000000001",
            clinic_id=str(other_clinic.id),
        ),
    )

    assert response.status_code == 200
    with as_clinic(clinic):
        assert CallLog.objects.filter(clinic=clinic).count() == 1
    with as_clinic(other_clinic):
        assert CallLog.objects.filter(clinic=other_clinic).count() == 0


@pytest.mark.django_db
def test_a_number_owned_by_another_clinic_routes_there(
    as_clinic, api_client, clinic, other_clinic, voice_number, other_voice_number
):
    from apps.conversations.models import CallLog

    response = _post_voice(
        api_client,
        _voice_payload(
            interaction_id="int-other-tenant",
            agent_phone_number="+919000000009",
        ),
    )

    assert response.status_code == 200
    with as_clinic(other_clinic):
        assert CallLog.objects.filter(clinic=other_clinic).count() == 1
    with as_clinic(clinic):
        assert CallLog.objects.filter(clinic=clinic).count() == 0


@pytest.mark.django_db
def test_a_call_to_an_unknown_number_is_not_attributed_to_any_clinic(
    as_clinic, api_client, clinic, voice_number
):
    """Fail closed: an unroutable event is stored, but owns no tenant."""
    from apps.conversations.models import CallLog
    from apps.integrations.models import ProviderEvent

    response = _post_voice(
        api_client,
        _voice_payload(interaction_id="int-unknown", agent_phone_number="+919999999999"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["processed"] == 0

    with as_clinic(clinic):
        assert CallLog.objects.filter(clinic=clinic).count() == 0
    stored = ProviderEvent.objects.get(provider_event_id="int-unknown")
    assert stored.clinic is None
    assert stored.status == "unrouted"


@pytest.mark.django_db
def test_a_mismatched_provider_in_the_url_is_refused(api_client, clinic, voice_number):
    """``/webhooks/voice/whatsapp/`` must not be handled by the voice view."""
    response = api_client.post(
        f"/api/v1/webhooks/voice/whatsapp/{WEBHOOK_SECRET}/",
        data=json.dumps(_voice_payload()),
        content_type="application/json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_an_unresolved_call_raises_a_follow_up_task(as_clinic, api_client, clinic, voice_number):
    from apps.conversations.models import FollowUpTask

    response = _post_voice(
        api_client,
        _voice_payload(
            interaction_id="int-unresolved",
            final_agent_variables={"call_outcome": "unresolved"},
        ),
    )

    assert response.status_code == 200
    with as_clinic(clinic):
        task = FollowUpTask.objects.filter(clinic=clinic).get()
    assert task.task_type == "unresolved_request"


@pytest.mark.django_db
def test_a_retried_unresolved_call_does_not_duplicate_the_task(
    as_clinic, api_client, clinic, voice_number
):
    from apps.conversations.models import FollowUpTask

    _post_voice(
        api_client,
        _voice_payload(
            interaction_id="int-unresolved-retry",
            final_agent_variables={"call_outcome": "unresolved"},
        ),
    )
    _post_voice(
        api_client,
        _voice_payload(
            interaction_id="int-unresolved-retry",
            final_agent_variables={"call_outcome": "unresolved"},
        ),
    )

    with as_clinic(clinic):
        assert FollowUpTask.objects.filter(clinic=clinic).count() == 1


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------
WHATSAPP_SECRET = "whatsapp-app-secret"


def _whatsapp_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _whatsapp_payload(message_id: str = "wamid.1", phone_number_id: str = "phone-1") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "+919000100001",
                                    "type": "text",
                                    "text": {"body": "I need an appointment"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


@pytest.fixture
def _whatsapp_secret():
    with override_settings(WHATSAPP_APP_SECRET=WHATSAPP_SECRET):
        yield


@pytest.mark.django_db
def test_a_whatsapp_webhook_with_a_forged_signature_is_rejected(
    _whatsapp_secret, api_client, clinic, whatsapp_number
):
    body = json.dumps(_whatsapp_payload()).encode()
    response = api_client.post(
        "/api/v1/webhooks/whatsapp/whatsapp/",
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=" + "0" * 64,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_signature"


@pytest.mark.django_db
def test_a_whatsapp_webhook_with_a_valid_signature_is_accepted(
    _whatsapp_secret, as_clinic, api_client, clinic, whatsapp_number
):
    from apps.conversations.models import ConversationMessage

    body = json.dumps(_whatsapp_payload()).encode()
    response = api_client.post(
        "/api/v1/webhooks/whatsapp/whatsapp/",
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_whatsapp_signature(body, WHATSAPP_SECRET),
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    with as_clinic(clinic):
        assert ConversationMessage.objects.filter(clinic=clinic).count() == 1


@pytest.mark.django_db
def test_a_duplicate_whatsapp_message_is_applied_once(
    _whatsapp_secret, as_clinic, api_client, clinic, whatsapp_number
):
    from apps.conversations.models import ConversationMessage

    body = json.dumps(_whatsapp_payload()).encode()
    signature = _whatsapp_signature(body, WHATSAPP_SECRET)
    for _ in range(2):
        response = api_client.post(
            "/api/v1/webhooks/whatsapp/whatsapp/",
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

    assert response.json()["duplicates"] == 1
    with as_clinic(clinic):
        assert ConversationMessage.objects.filter(clinic=clinic).count() == 1


@pytest.mark.django_db
def test_the_meta_verification_handshake_requires_the_configured_token(
    _whatsapp_secret, api_client
):
    rejected = api_client.get(
        "/api/v1/webhooks/whatsapp/whatsapp/",
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "123"},
    )
    assert rejected.status_code == 403

    accepted = api_client.get(
        "/api/v1/webhooks/whatsapp/whatsapp/",
        {
            "hub.mode": "subscribe",
            "hub.verify_token": WHATSAPP_SECRET,
            "hub.challenge": "123",
        },
    )
    assert accepted.status_code == 200
    assert accepted.content == b"123"
