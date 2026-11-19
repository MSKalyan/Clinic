"""WhatsApp appointment confirmations and inbound patient messages.

All WAHA HTTP traffic is mocked: these tests prove the wiring from a booking
lifecycle event to the outgoing text, and from a patient reply to a linked
conversation in the dashboard.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.appointments.services.booking import BookingService
from apps.core.constants import Channel
from apps.integrations.providers.waha import IncomingWahaMessage

SETTINGS = {
    "WAHA_API_KEY": "test-key",
    "WAHA_BASE_URL": "http://waha:3000",
    "WAHA_SESSION": "session_01",
    "WAHA_MAX_TEXT_LENGTH": 4096,
    "WAHA_DEFAULT_REPLY": "Thanks for your message. We will get back to you.",
    "WAHA_AUTO_REPLIES": {},
    # Run delivery inline so the tests exercise the full path deterministically.
    "MESSAGES_ASYNC": False,
}


def _ok(message_id: str = "wa-out-1") -> SimpleNamespace:
    return SimpleNamespace(ok=True, data={"id": message_id}, error="", status_code=200)


@pytest.fixture(autouse=True)
def _settings():
    with override_settings(**SETTINGS):
        yield


@pytest.mark.django_db
def test_booking_sends_a_whatsapp_confirmation(
    scoped, doctor, patient, slot_time, django_capture_on_commit_callbacks
):
    with patch(
        "apps.integrations.services.waha.send_text_message", return_value=_ok()
    ) as send, django_capture_on_commit_callbacks(execute=True):
        appointment = BookingService.book(
            clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
        )

    assert send.call_count == 1
    chat_id, text = send.call_args.args
    assert chat_id == "919000100001@c.us"
    assert appointment.reference in text
    assert doctor.name in text
    assert patient.name in text


@pytest.mark.django_db
def test_reschedule_and_cancel_send_their_own_messages(
    scoped, doctor, patient, slot_time, django_capture_on_commit_callbacks
):
    with patch(
        "apps.integrations.services.waha.send_text_message", return_value=_ok()
    ) as send:
        with django_capture_on_commit_callbacks(execute=True):
            appointment = BookingService.book(
                clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
            )
        assert send.call_count == 1

        with django_capture_on_commit_callbacks(execute=True):
            BookingService.reschedule(
                appointment=appointment, new_start_at=slot_time + timedelta(days=7)
            )
        assert send.call_count == 2
        assert "rescheduled" in send.call_args.args[1].lower()

        with django_capture_on_commit_callbacks(execute=True):
            BookingService.cancel(appointment=appointment, reason="Patient request")
        assert send.call_count == 3
        assert "cancelled" in send.call_args.args[1].lower()
        assert "Patient request" in send.call_args.args[1]


@pytest.mark.django_db
def test_opted_out_patient_receives_no_confirmation(
    scoped, doctor, patient, slot_time, django_capture_on_commit_callbacks
):
    patient.communication_preferences = {"opt_out_whatsapp": True}
    patient.save(update_fields=["communication_preferences"])

    with (
        patch("apps.integrations.services.waha.send_text_message") as send,
        django_capture_on_commit_callbacks(execute=True),
    ):
        BookingService.book(
            clinic=scoped, doctor=doctor, patient=patient, start_at=slot_time
        )

    send.assert_not_called()


@pytest.mark.django_db
def test_inbound_reply_is_linked_to_the_patient_conversation(
    scoped, patient, as_clinic
):
    from apps.conversations.models import Conversation

    incoming = IncomingWahaMessage(
        session="session_01",
        message_id="false_919000100001@c.us_MSG1",
        sender_id="919000100001@c.us",
        sender_phone="+919000100001",
        text="Hi",
        timestamp=None,
        chat_id="919000100001@c.us",
    )

    from apps.integrations.services.waha_flow import process_incoming

    with patch("apps.integrations.services.waha.send_text_message", return_value=_ok()):
        summary = process_incoming(incoming)

    assert summary["accepted"] == 1
    assert summary["linked"] == 1
    assert summary["replied"] == 1

    with as_clinic(scoped):
        conversation = Conversation.objects.get(
            patient=patient, channel=Channel.WHATSAPP, provider_conversation_id=incoming.chat_id
        )
        assert conversation.messages.filter(direction="inbound").count() == 1
        assert conversation.messages.filter(direction="outbound").count() == 1
