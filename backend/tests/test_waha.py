"""WAHA integration tests: REST client, webhook parsing and receive/reply flow.

WAHA HTTP traffic is always mocked -- no real WhatsApp account is involved.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from django.test import Client, override_settings

from apps.integrations.providers.waha import WahaAdapter
from apps.integrations.services.waha import (
    get_session_status,
    get_waha_health,
    send_text_message,
)
from apps.integrations.services.waha_flow import generate_auto_reply, process_webhook

WEBHOOK_SECRET = "test-webhook-secret"
HMAC_KEY = "test-hmac-key"
API_KEY = "test-api-key"
BASE_URL = "http://waha:3000"
SESSION = "session_01"

WAHA_SETTINGS = {
    "WAHA_BASE_URL": BASE_URL,
    "WAHA_API_KEY": API_KEY,
    "WAHA_SESSION": SESSION,
    "WAHA_WEBHOOK_SECRET": WEBHOOK_SECRET,
    "WAHA_WEBHOOK_HMAC_KEY": HMAC_KEY,
    "WAHA_REQUEST_TIMEOUT_SECONDS": 5.0,
    "WAHA_MAX_TEXT_LENGTH": 4096,
    "WAHA_CLINIC_SLUG": "",
    "MESSAGES_ASYNC": False,
}


@pytest.fixture(autouse=True)
def _waha_settings():
    with override_settings(**WAHA_SETTINGS):
        yield


@pytest.fixture
def waha_clinic(clinic, doctor, settings):
    """A clinic with a doctor that this WAHA number is mapped to."""
    settings.WAHA_CLINIC_SLUG = clinic.slug
    return clinic


def _adapter() -> WahaAdapter:
    return WahaAdapter(
        webhook_secret=WEBHOOK_SECRET, hmac_key=HMAC_KEY, session=SESSION
    )


def _message_payload(
    *,
    message_id: str = "false_15550000000@c.us_ABC123",
    body: str = "Hi",
    from_id: str = "15550000000@c.us",
    from_me: bool = False,
    event: str = "message",
    session: str = SESSION,
) -> dict:
    return {
        "id": "evt_01aaaaaaaaaaaaaaaaaaaaaaaa",
        "timestamp": 1763200000000,
        "event": event,
        "session": session,
        "engine": "WEBJS",
        "payload": {
            "id": message_id,
            "timestamp": 1763200000,
            "from": from_id,
            "to": "15550000001@c.us",
            "fromMe": from_me,
            "body": body,
            "hasMedia": False,
        },
    }


def _signed_post(client: Client, payload: dict, *, secret: str = WEBHOOK_SECRET, hmac_key: str = HMAC_KEY, body: bytes | None = None):
    raw = body if body is not None else json.dumps(payload).encode()
    return client.post(
        "/api/v1/webhooks/waha/",
        data=raw,
        content_type="application/json",
        HTTP_X_WEBHOOK_SECRET=secret,
        HTTP_X_WEBHOOK_HMAC=hmac.new(hmac_key.encode(), raw, hashlib.sha512).hexdigest(),
        HTTP_X_WEBHOOK_HMAC_ALGORITHM="sha512",
    )


class _FakeResponse:
    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body if body is not None else {"id": "sent-1", "timestamp": 1}

    def json(self) -> dict:
        return self._body


def _ok_result(message_id: str = "sent-1"):
    """A successful WahaResult-shaped value for service-layer patches."""
    return SimpleNamespace(ok=True, data={"id": message_id}, error="", status_code=200)


# ---------------------------------------------------------------------------
# WAHA REST client (unit tests)
# ---------------------------------------------------------------------------
def test_successful_outgoing_message_request():
    with patch("apps.integrations.services.waha.requests.request", return_value=_FakeResponse()) as call:
        result = send_text_message("15550000000@c.us", "Hello!")

    assert result.ok is True
    assert result.data == {"id": "sent-1", "timestamp": 1}
    args, kwargs = call.call_args
    assert args == ("POST", f"{BASE_URL}/api/sendText")
    assert kwargs["json"] == {
        "session": SESSION,
        "chatId": "15550000000@c.us",
        "text": "Hello!",
    }
    assert kwargs["timeout"] == 5.0


def test_waha_api_authentication_header():
    with patch("apps.integrations.services.waha.requests.request", return_value=_FakeResponse()) as call:
        send_text_message("15550000000@c.us", "Hello!")
    assert call.call_args.kwargs["headers"]["X-Api-Key"] == API_KEY


def test_waha_connection_failure_returns_structured_error():
    with patch(
        "apps.integrations.services.waha.requests.request",
        side_effect=requests.ConnectionError("refused"),
    ):
        result = send_text_message("15550000000@c.us", "Hello!")
    assert result.ok is False
    assert "unreachable" in result.error


def test_waha_timeout_returns_structured_error():
    with patch(
        "apps.integrations.services.waha.requests.request",
        side_effect=requests.Timeout("slow"),
    ):
        result = get_session_status()
    assert result.ok is False
    assert "timed out" in result.error


def test_waha_http_error_is_reported_without_leaking_body():
    with patch(
        "apps.integrations.services.waha.requests.request",
        return_value=_FakeResponse(401, {"error": "secret leaked here"}),
    ):
        result = get_waha_health()
    assert result.ok is False
    assert result.status_code == 401
    assert "secret leaked here" not in result.error


def test_invalid_json_response_is_reported():
    response = _FakeResponse()
    response.json = lambda: (_ for _ in ()).throw(ValueError("bad json"))  # type: ignore[method-assign]
    with patch("apps.integrations.services.waha.requests.request", return_value=response):
        result = get_session_status()
    assert result.ok is False
    assert "invalid response" in result.error


@pytest.mark.parametrize("recipient", ["", "   ", None, "123@g.us", "bad id@c.us"])
def test_invalid_recipient_is_rejected_before_any_http_call(recipient):
    with patch("apps.integrations.services.waha.requests.request") as call:
        result = send_text_message(recipient, "Hello!")
    assert result.ok is False
    call.assert_not_called()


# ---------------------------------------------------------------------------
# Webhook parsing / filtering (unit tests)
# ---------------------------------------------------------------------------
def test_incoming_webhook_payload_parsing():
    incoming = _adapter().parse_incoming(_message_payload())
    assert incoming is not None
    assert incoming.session == SESSION
    assert incoming.message_id == "false_15550000000@c.us_ABC123"
    assert incoming.sender_id == "15550000000@c.us"
    assert incoming.sender_phone == "+15550000000"
    assert incoming.text == "Hi"
    assert incoming.timestamp is not None


def test_outgoing_message_event_is_ignored():
    assert _adapter().parse_incoming(_message_payload(from_me=True)) is None


def test_group_message_is_ignored():
    payload = _message_payload(from_id="120363012345678901@g.us")
    payload["payload"]["author"] = "15550000000@c.us"
    assert _adapter().parse_incoming(payload) is None


def test_unrelated_events_and_status_updates_are_ignored():
    for event in ("message.ack", "session.status", "message.reaction", "message.any"):
        assert _adapter().parse_incoming(_message_payload(event=event)) is None


def test_session_from_another_waha_session_is_ignored():
    assert _adapter().parse_incoming(_message_payload(session="other")) is None


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"event": "message"}, {"event": "message", "payload": "not-a-dict"}],
)
def test_malformed_payloads_are_handled_safely(payload):
    assert _adapter().parse_incoming(payload) is None


def test_webhook_authentication_rejects_bad_secret_and_bad_hmac():
    payload = _message_payload()
    bad_secret = _signed_post(Client(), payload, secret="wrong")
    assert bad_secret.status_code == 403

    bad_hmac = _signed_post(Client(), payload, hmac_key="wrong")
    assert bad_hmac.status_code == 403


def test_webhook_rejects_malformed_json():
    response = _signed_post(Client(), None, body=b"{not-json")
    assert response.status_code == 400


def test_automated_response_generation(waha_clinic):
    reply = generate_auto_reply("Hi, I want to know about your clinic.", waha_clinic)
    assert waha_clinic.name in reply
    assert "Reply with the number" in reply
    assert generate_auto_reply("anything", waha_clinic) == reply


# ---------------------------------------------------------------------------
# End-to-end flow through the Django webhook (integration tests, mocked WAHA)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_valid_incoming_event_is_logged_and_replied_to(waha_clinic):
    from apps.integrations.models import WahaMessageLog

    with patch("apps.integrations.services.waha.send_text_message", return_value=_ok_result("out-1")) as send:
        response = _signed_post(Client(), _message_payload())

    assert response.status_code == 200
    assert response.json()["replied"] == 1
    log = WahaMessageLog.objects.get(message_id="false_15550000000@c.us_ABC123")
    assert log.direction == "INBOUND"
    assert log.status == "REPLIED"
    assert log.sender_phone == "+15550000000"
    assert log.text == "Hi"
    assert log.reply_message_id == "out-1"
    send.assert_called_once()
    assert waha_clinic.name in send.call_args.args[1]


@pytest.mark.django_db
def test_message_other_than_exact_hi_is_logged_but_not_answered(waha_clinic):
    from apps.integrations.models import WahaMessageLog

    with patch("apps.integrations.services.waha.send_text_message") as send:
        response = _signed_post(Client(), _message_payload(body="Hello there"))

    assert response.status_code == 200
    assert response.json()["replied"] == 0
    assert response.json()["skipped"] == 1
    log = WahaMessageLog.objects.get()
    assert log.text == "Hello there"
    assert log.status == "SKIPPED"
    send.assert_not_called()


@pytest.mark.django_db
def test_long_waha_message_id_is_stored_without_a_db_error(patient):
    """Real WAHA ids exceed the 200-char log/thread columns (found in prod)."""
    from apps.conversations.models import ConversationMessage
    from apps.integrations.models import WahaMessageLog

    patient.phone = "+15550000000"
    patient.save(update_fields=["phone"])
    long_id = "false_15550000000@c.us_" + "x" * 220
    assert len(long_id) > 200

    with patch("apps.integrations.services.waha.send_text_message", return_value=_ok_result()):
        response = _signed_post(Client(), _message_payload(message_id=long_id))

    assert response.status_code == 200, response.content
    assert WahaMessageLog.objects.filter(message_id=long_id).exists()
    assert ConversationMessage.objects.filter(direction="inbound").exists()
    stored = ConversationMessage.objects.get(direction="inbound")
    assert len(stored.provider_message_id) <= 200


@pytest.mark.django_db
def test_record_outbound_truncates_long_provider_id(patient):
    from apps.conversations.services.messages import record_outbound

    conversation, message = record_outbound(
        patient.clinic, patient, "Hello", provider_message_id="w" * 220
    )
    assert conversation is not None and message is not None
    assert len(message.provider_message_id) == 200


@pytest.mark.django_db
def test_duplicate_webhook_does_not_generate_a_second_reply():
    from apps.integrations.models import WahaMessageLog

    payload = _message_payload()
    with patch("apps.integrations.services.waha.send_text_message", return_value=_ok_result()) as send:
        first = _signed_post(Client(), payload)
        second = _signed_post(Client(), payload)

    assert first.json()["accepted"] == 1
    assert second.json()["duplicates"] == 1
    assert send.call_count == 1
    assert WahaMessageLog.objects.filter(message_id=payload["payload"]["id"]).count() == 1


@pytest.mark.django_db
def test_each_message_advances_the_assistant_without_repeating(waha_clinic):
    """A second, different message gets the *next* prompt, not the same greeting."""
    from apps.integrations.models import WhatsAppFlow

    first = _message_payload()
    second = _message_payload()
    second["payload"]["id"] = "false_15550000000@c.us_DIFFERENT"
    second["payload"]["body"] = "1"

    with patch("apps.integrations.services.waha.send_text_message", return_value=_ok_result()) as send:
        first_result = _signed_post(Client(), first)
        second_result = _signed_post(Client(), second)

    assert first_result.json()["replied"] == 1
    assert second_result.json()["replied"] == 1
    assert send.call_count == 2
    assert "Reply with the number" in send.call_args_list[0].args[1]
    assert "full name" in send.call_args_list[1].args[1]
    flow = WhatsAppFlow.objects.get(chat_id="15550000000@c.us")
    assert flow.state == WhatsAppFlow.State.NAME


@pytest.mark.django_db
def test_integration_flow_uses_the_expected_waha_api_request(waha_clinic):
    """The flow reaches the service layer, which builds the real WAHA payload."""
    with patch("apps.integrations.services.waha.requests.request", return_value=_FakeResponse()) as call:
        summary = process_webhook(_message_payload(), adapter=_adapter())

    assert summary["replied"] == 1
    assert call.call_args.args == ("POST", f"{BASE_URL}/api/sendText")
    assert waha_clinic.name in call.call_args.kwargs["json"]["text"]
    assert call.call_args.kwargs["headers"]["X-Api-Key"] == API_KEY


@pytest.mark.django_db
def test_failed_waha_send_is_logged_without_exposing_credentials():
    from apps.integrations.models import WahaMessageLog

    failed = type("R", (), {"ok": False, "data": None, "error": "WAHA is unreachable.", "status_code": None})()
    with patch("apps.integrations.services.waha.send_text_message", return_value=failed):
        response = _signed_post(Client(), _message_payload())

    assert response.status_code == 200
    # The webhook acknowledges the message and queues the acknowledgement;
    # the delivery failure is recorded on the log row (no credentials leaked).
    log = WahaMessageLog.objects.get()
    assert log.status == "FAILED"
    assert API_KEY not in log.error
    assert HMAC_KEY not in log.error


@pytest.mark.django_db
def test_ignored_webhook_writes_no_message_log():
    from apps.integrations.models import WahaMessageLog

    with patch("apps.integrations.services.waha.send_text_message") as send:
        response = _signed_post(Client(), _message_payload(from_me=True))
    assert response.json()["ignored"] == 1
    assert WahaMessageLog.objects.count() == 0
    send.assert_not_called()


# ---------------------------------------------------------------------------
# Authenticated internal send endpoint
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_send_endpoint_requires_authentication(api_client):
    response = api_client.post(
        "/api/v1/integrations/waha/messages/",
        {"chat_id": "15550000000@c.us", "text": "Hello!"},
        format="json",
    )
    # The project's first DRF authenticator (service token) does not advertise
    # a WWW-Authenticate challenge, so DRF returns 403 rather than 401 here.
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_authenticated_send_endpoint_calls_waha(auth_client):
    with patch("apps.integrations.services.waha.send_text_message", return_value=_ok_result()) as send:
        response = auth_client.post(
            "/api/v1/integrations/waha/messages/",
            {"chat_id": "15550000000@c.us", "text": "Hello!"},
            format="json",
        )
    assert response.status_code == 202
    assert response.json()["status"] in {"queued", "sent"}
    assert response.json()["idempotency_key"]
    send.assert_called_once_with("15550000000@c.us", "Hello!")
