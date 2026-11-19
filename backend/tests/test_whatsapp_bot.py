"""WhatsApp booking assistant: dynamic prompts and end-to-end appointment flow."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.core.rls import rls_scope
from apps.core.timeutils import clinic_zone
from apps.integrations.models import WahaMessageLog, WhatsAppFlow
from apps.integrations.providers.waha import IncomingWahaMessage
from apps.integrations.services.waha_flow import process_incoming

CHAT_ID = "916281013594@c.us"
PHONE = "+916281013594"


@pytest.fixture(autouse=True)
def waha_clinic(clinic, doctor, second_doctor, settings):
    """Map this WAHA number to a clinic that has doctors with rotas."""
    settings.WAHA_CLINIC_SLUG = clinic.slug
    settings.MESSAGES_ASYNC = False
    return clinic


@pytest.fixture(autouse=True)
def replies():
    """Capture every text the assistant asks WAHA to deliver."""
    captured: list[str] = []
    result = SimpleNamespace(ok=True, data={"id": "out-1"}, error="", status_code=200)

    def _send(_chat_id: str, text: str):
        captured.append(text)
        return result

    with patch("apps.integrations.services.waha.send_text_message", side_effect=_send):
        yield captured


def _incoming(text: str, number: int) -> IncomingWahaMessage:
    return IncomingWahaMessage(
        session="session_01",
        message_id=f"false_916281013594@c.us_BOT{number:03d}",
        sender_id=CHAT_ID,
        sender_phone=PHONE,
        text=text,
        timestamp=timezone.now(),
        chat_id=CHAT_ID,
    )


def _send(text: str, number: int, replies: list[str]) -> str:
    summary = process_incoming(_incoming(text, number))
    assert summary["replied"] == 1, summary
    return replies[-1]


def _no_reply(text: str, number: int, replies: list[str]) -> dict:
    before = len(replies)
    summary = process_incoming(_incoming(text, number))
    assert summary["replied"] == 0, summary
    assert summary["skipped"] == 1, summary
    assert len(replies) == before
    return summary


def _next_weekday(clinic) -> str:
    day = datetime.now(clinic_zone(clinic)).date() + timedelta(days=1)
    while day.weekday() >= 5:  # skip Sunday
        day += timedelta(days=1)
    return day.isoformat()


def _flow():
    return WhatsAppFlow.objects.get(chat_id=CHAT_ID)


@pytest.mark.django_db
def test_menu_uses_live_clinic_data(waha_clinic, replies):
    text = _send("hi", 1, replies)

    assert waha_clinic.name in text
    assert "Cardiology" in text
    assert "Reply with the number" in text
    assert _flow().state == WhatsAppFlow.State.MENU


@pytest.mark.django_db
def test_menu_info_option_lists_doctors_and_specialities(waha_clinic, doctor, replies):
    _send("hi", 1, replies)
    text = _send("3", 2, replies)

    assert doctor.name in text
    assert doctor.specialization in text
    assert "1. Book an appointment" in text


@pytest.mark.django_db
def test_full_flow_creates_patient_and_appointment_in_back_office(waha_clinic, doctor, replies):
    from apps.appointments.models import Appointment, Patient
    from apps.conversations.models import Conversation
    from apps.core.constants import BookingSource

    date_text = _next_weekday(waha_clinic)
    _send("hi", 1, replies)
    assert "full name" in _send("1", 2, replies)
    assert "phone number" in _send("Ravi Kumar", 3, replies)
    reply = _send(PHONE, 4, replies)
    assert doctor.name in reply
    assert "Choose a doctor" in reply
    assert "YYYY-MM-DD" in _send("1", 5, replies)
    assert "Free times" in _send(date_text, 6, replies)
    assert "Please confirm your booking" in _send("1", 7, replies)
    confirmation = _send("YES", 8, replies)

    assert "APT" in confirmation
    with rls_scope(str(waha_clinic.id)):
        patient = Patient.objects.get(phone=PHONE)
        assert patient.name == "Ravi Kumar"
        appointment = Appointment.objects.get(patient=patient)
        assert appointment.booking_source == BookingSource.WHATSAPP
        assert Conversation.objects.filter(
            patient=patient, provider_conversation_id=CHAT_ID
        ).exists()

    flow = _flow()
    assert flow.state == WhatsAppFlow.State.DONE
    assert flow.context["appointment_reference"] == appointment.reference


@pytest.mark.django_db
def test_online_consultation_is_recorded(waha_clinic, replies):
    from apps.appointments.models import Appointment

    _send("hi", 1, replies)
    _send("2", 2, replies)
    _send("Ravi Kumar", 3, replies)
    _send(PHONE, 4, replies)
    _send("1", 5, replies)
    _send(_next_weekday(waha_clinic), 6, replies)
    assert "Online consultation" in _send("1", 7, replies)
    _send("yes", 8, replies)

    with rls_scope(str(waha_clinic.id)):
        assert "Online consultation" in Appointment.objects.get().notes


@pytest.mark.django_db
def test_invalid_answers_do_not_advance_flow(waha_clinic, replies):
    _send("hi", 1, replies)
    assert "Reply with the number" in _send("pizza", 2, replies)
    assert "full name" in _send("1", 3, replies)
    assert "full name" in _send("x", 4, replies)
    assert _flow().state == WhatsAppFlow.State.NAME


@pytest.mark.django_db
def test_cancel_returns_to_menu_without_booking(waha_clinic, replies):
    from apps.appointments.models import Appointment

    _send("hi", 1, replies)
    _send("1", 2, replies)
    _send("Ravi Kumar", 3, replies)
    _send(PHONE, 4, replies)
    _send("1", 5, replies)
    _send(_next_weekday(waha_clinic), 6, replies)
    _send("1", 7, replies)
    assert "nothing was booked" in _send("no", 8, replies)

    with rls_scope(str(waha_clinic.id)):
        assert Appointment.objects.count() == 0
    assert _flow().state == WhatsAppFlow.State.MENU


@pytest.mark.django_db
def test_handoff_option_never_books(waha_clinic, replies):
    from apps.appointments.models import Appointment

    _send("hi", 1, replies)
    assert "team" in _send("4", 2, replies)
    assert _flow().state == WhatsAppFlow.State.HANDOFF
    with rls_scope(str(waha_clinic.id)):
        assert Appointment.objects.count() == 0


@pytest.mark.django_db
def test_restart_after_booking_starts_a_new_flow(waha_clinic, replies):
    _send("hi", 1, replies)
    _send("1", 2, replies)
    _send("Ravi Kumar", 3, replies)
    _send(PHONE, 4, replies)
    _send("1", 5, replies)
    _send(_next_weekday(waha_clinic), 6, replies)
    _send("1", 7, replies)
    _send("yes", 8, replies)

    assert "How can we help" in _send("hi", 9, replies)
    assert _flow().state == WhatsAppFlow.State.MENU


@pytest.mark.django_db
def test_only_exact_hi_starts_the_flow(waha_clinic, replies):
    for number, text in enumerate(("hello", "Hey", "start", "menu", "hi there"), 1):
        _no_reply(text, number, replies)

    # The messages were still stored and can be seen by the clinic.
    with rls_scope(str(waha_clinic.id)):
        assert WahaMessageLog.objects.filter(
            direction=WahaMessageLog.Direction.INBOUND
        ).count() == 5
    assert WhatsAppFlow.objects.filter(chat_id=CHAT_ID).count() == 0

    assert waha_clinic.name in _send("Hi", 6, replies)
    assert _flow().state == WhatsAppFlow.State.MENU


@pytest.mark.django_db
def test_no_reply_after_booking_until_a_fresh_hi(waha_clinic, replies):
    _send("hi", 1, replies)
    _send("1", 2, replies)
    _send("Ravi Kumar", 3, replies)
    _send(PHONE, 4, replies)
    _send("1", 5, replies)
    _send(_next_weekday(waha_clinic), 6, replies)
    _send("1", 7, replies)
    _send("yes", 8, replies)

    assert _flow().state == WhatsAppFlow.State.DONE
    _no_reply("thank you", 9, replies)
    _no_reply("Can I change it?", 10, replies)
    assert _flow().state == WhatsAppFlow.State.DONE

    assert "How can we help" in _send("HI", 11, replies)
    assert _flow().state == WhatsAppFlow.State.MENU
