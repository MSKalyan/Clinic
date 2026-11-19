"""WhatsApp booking assistant.

Patients only use WhatsApp; the website is a back office. This module drives a
small state machine per chat (see ``WhatsAppFlow``) and renders every prompt
from live clinic data -- doctors, specialities, opening hours and real free
slots. Booking goes through ``BookingService`` so an appointment made in a
chat is indistinguishable from one made by staff in the dashboard.

The webhook never calls WAHA: it persists the log and the next state, then
queues delivery through the existing Celery task.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from apps.conversations.services.templates import render_template
from apps.core.constants import ClinicStatus
from apps.integrations.models import WahaMessageLog, WhatsAppFlow

logger = logging.getLogger("apps.integrations.bot")

MENU_OPTIONS = (
    "1. Book an appointment\n"
    "2. Online consultation\n"
    "3. Doctors & specialities\n"
    "4. Talk to our team"
)

#: A conversation begins only when the patient sends exactly this word.
_START_WORD = "hi"
_YES_WORDS = {"yes", "y", "confirm", "ok", "okay", "haan"}
_NO_WORDS = {"no", "n", "cancel", "stop"}
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_DAY_LABELS = {
    "mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu",
    "fri": "Fri", "sat": "Sat", "sun": "Sun",
}


def _words(text: str) -> list[str]:
    return "".join(char.lower() if char.isalnum() else " " for char in text or "").split()


def _first(text: str) -> str:
    words = _words(text)
    return words[0] if words else ""


def _choice(text: str) -> int | None:
    """Read a numbered answer such as '2', '2)', 'two' or 'option 2'."""
    for word in _words(text):
        if word.isdigit():
            return int(word)
        if word in _WORD_NUMBERS:
            return _WORD_NUMBERS[word]
    return None


def _is_start(text: str) -> bool:
    """True only for an exact ``Hi`` (case/punctuation insensitive).

    ``Hello``, ``hi there``, ``menu`` and similar messages must not start or
    restart the flow.
    """
    return " ".join(_words(text)) == _START_WORD


def _normalise(value: str) -> str:
    from apps.core.utils import normalise_phone

    return normalise_phone(value or "")


def _save(flow: WhatsAppFlow) -> None:
    flow.save(update_fields=["state", "context", "updated_at"])


# -- clinic resolution -------------------------------------------------------

def resolve_clinic(sender_phone: str):
    """Find the clinic this sender belongs to.

    An existing patient wins. Otherwise the number is mapped to the clinic
    configured for this WAHA session; if there is exactly one active clinic,
    that is used as a safe default.
    """
    from apps.tenancy.models import Clinic

    normalised = _normalise(sender_phone)
    if normalised:
        from apps.appointments.models import Patient

        patient = (
            Patient.objects.filter(phone=normalised, is_active=True)
            .order_by("-created_at")
            .first()
        )
        if patient is not None:
            return patient.clinic

    slug = getattr(settings, "WAHA_CLINIC_SLUG", "")
    if slug:
        # The mapping is explicit, so an onboarding clinic can still be served
        # while it is being set up; only the implicit fallback needs ACTIVE.
        clinic = Clinic.objects.filter(slug=slug).first()
        if clinic is not None:
            return clinic

    active = list(Clinic.objects.filter(status=ClinicStatus.ACTIVE).order_by("name"))
    return active[0] if len(active) == 1 else None


# -- dynamic message content -------------------------------------------------

def _specialities(clinic) -> str:
    from apps.doctors.models import Doctor

    values = (
        Doctor.objects.filter(clinic=clinic, is_active=True)
        .exclude(specialization="")
        .values_list("specialization", flat=True)
        .distinct()
        .order_by("specialization")
    )
    return ", ".join(values) if values else "General medicine"


def _hours(clinic) -> str:
    hours = clinic.operating_hours() or {}
    parts = []
    for key, label in _DAY_LABELS.items():
        rule = hours.get(key) or {}
        if rule.get("closed"):
            parts.append(f"{label} closed")
        elif rule.get("open") and rule.get("close"):
            parts.append(f"{label} {rule['open']}-{rule['close']}")
    return ", ".join(parts) if parts else "Please call the clinic"


def _next_available(clinic) -> str:
    from apps.appointments.services.availability import AvailabilityService

    now = timezone.now()
    try:
        slots = AvailabilityService(clinic).slots(
            from_dt=now, to_dt=now + timedelta(days=7)
        )
        free = [slot for slot in slots if slot.available]
    except Exception:  # pragma: no cover - a summary must never break the menu
        logger.exception("could not build availability summary for %s", clinic.slug)
        return "ask our team for the next opening"
    if not free:
        return "no times in the next 7 days - please message our team"
    slot = free[0]
    return f"{slot.doctor_name}, {slot.local_date} at {slot.display_start}"


def _active_doctors(clinic):
    from apps.doctors.models import Doctor

    return list(
        Doctor.objects.filter(clinic=clinic, is_active=True).order_by("sort_order", "name")
    )


def _doctor_lines(doctors) -> str:
    lines = []
    for number, doctor in enumerate(doctors, 1):
        suffix = f" ({doctor.specialization})" if doctor.specialization else ""
        lines.append(f"{number}. {doctor.name}{suffix}")
    return "\n".join(lines)


def _slots_for(clinic, doctor, on_date: date):
    from apps.appointments.services.availability import AvailabilityService

    slots = AvailabilityService(clinic).slots(doctors=[doctor], on_date=on_date)
    return [slot for slot in slots if slot.available][:12]


def _slot_lines(slots) -> str:
    return "\n".join(
        f"{number}. {slot.display_start}" for number, slot in enumerate(slots, 1)
    )


def _local_today(clinic) -> date:
    from apps.core.timeutils import clinic_zone

    return datetime.now(clinic_zone(clinic)).date()


def _parse_date(text: str, clinic) -> date | None:
    cleaned = " ".join(_words(text))
    if cleaned == "today":
        return _local_today(clinic)
    if cleaned == "tomorrow":
        return _local_today(clinic) + timedelta(days=1)
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


# -- conversation threading --------------------------------------------------

def _link_chat_to_patient(clinic, patient, chat_id: str) -> None:
    """Backfill the WAHA chat into the patient's back-office thread."""
    from apps.conversations.models import Conversation, ConversationMessage
    from apps.core.constants import Channel
    from apps.core.rls import rls_scope
    from apps.realtime.broadcast import conversation_changed, dashboard_changed

    with rls_scope(str(clinic.id)):
        conversation, _ = Conversation.objects.get_or_create(
            clinic=clinic,
            patient=patient,
            channel=Channel.WHATSAPP,
            provider_conversation_id=chat_id,
            defaults={
                "language": patient.preferred_language,
                "summary": f"WhatsApp with {patient.name or 'patient'}",
                "started_at": timezone.now(),
            },
        )
        logs = WahaMessageLog.objects.filter(
            sender_phone=patient.phone, direction=WahaMessageLog.Direction.INBOUND
        ).order_by("created_at")
        for log in logs:
            message, created = ConversationMessage.objects.get_or_create(
                clinic=clinic,
                conversation=conversation,
                direction="inbound",
                provider_message_id=log.message_id[:200],
                defaults={
                    "message_type": "text",
                    "excerpt": (log.text or "")[:280],
                },
            )
            if created:
                conversation_changed(
                    clinic.id,
                    conversation.id,
                    "message",
                    message={
                        "id": str(message.id),
                        "direction": "inbound",
                        "message_type": "text",
                        "excerpt": message.excerpt,
                        "created_at": message.created_at.isoformat(),
                    },
                )
        dashboard_changed(clinic.id, "conversation", conversation_id=str(conversation.id))


# -- prompts -----------------------------------------------------------------

def _menu(clinic, hint: str = "") -> str:
    text = render_template(
        "bot_menu",
        {
            "clinic_name": clinic.name,
            "specialities": _specialities(clinic),
            "hours": _hours(clinic),
            "availability": _next_available(clinic),
            "options": MENU_OPTIONS,
        },
    )
    return f"{hint}\n\n{text}" if hint else text


def _info(clinic) -> str:
    doctors = _active_doctors(clinic)
    return render_template(
        "bot_info",
        {
            "clinic_name": clinic.name,
            "specialities": _specialities(clinic),
            "doctors": _doctor_lines(doctors) or "Please call us.",
            "hours": _hours(clinic),
            "options": MENU_OPTIONS,
        },
    )


def _doctor_prompt(clinic, flow, hint: str = "") -> str:
    doctors = _active_doctors(clinic)
    flow.context["doctor_ids"] = [str(doctor.id) for doctor in doctors]
    flow.state = WhatsAppFlow.State.DOCTOR
    _save(flow)
    text = render_template("bot_doctors", {"doctors": _doctor_lines(doctors)})
    return f"{hint}\n\n{text}" if hint else text


def _date_prompt(clinic, hint: str = "") -> str:
    hint = hint or f"Next opening: {_next_available(clinic)}"
    return render_template("bot_date", {"hint": hint})


def _slot_prompt(clinic, doctor, on_date: date, flow, hint: str = "") -> str:
    slots = _slots_for(clinic, doctor, on_date)
    flow.context["slot_starts"] = [slot.start_at.isoformat() for slot in slots]
    flow.state = WhatsAppFlow.State.SLOT
    _save(flow)
    text = render_template(
        "bot_slots",
        {
            "doctor_name": doctor.name,
            "date": on_date.isoformat(),
            "slots": _slot_lines(slots) or "No free times on this date.",
        },
    )
    return f"{hint}\n\n{text}" if hint else text


def _confirm_prompt(clinic, flow, doctor, start_at: datetime, service: str) -> str:
    local = start_at.astimezone(ZoneInfo(clinic.timezone))
    flow.state = WhatsAppFlow.State.CONFIRM
    _save(flow)
    return render_template(
        "bot_confirm",
        {
            "name": flow.context.get("name", ""),
            "phone": flow.context.get("phone", ""),
            "service": service,
            "doctor_name": doctor.name,
            "when": local.strftime("%a %d %b, %I:%M %p"),
            "timezone": clinic.timezone,
        },
    )


def _book(clinic, flow, doctor, patient, service: str) -> str:
    from apps.appointments.services.booking import BookingService
    from apps.core.constants import BookingSource
    from apps.core.exceptions import DomainError, SlotUnavailable

    slot_start = flow.context["slot_start"]
    try:
        appointment = BookingService.book(
            clinic=clinic,
            doctor=doctor,
            patient=patient,
            start_at=datetime.fromisoformat(slot_start),
            source=BookingSource.WHATSAPP,
            notes=f"Booked via WhatsApp - {service}",
            idempotency_key=f"whatsapp-flow:{flow.pk}:{slot_start}",
            actor_type="whatsapp_bot",
        )
    except SlotUnavailable:
        flow.state = WhatsAppFlow.State.SLOT
        _save(flow)
        return render_template(
            "bot_unknown", {"hint": "That time was just taken. Please choose another."}
        )
    except DomainError:
        logger.exception("WhatsApp booking failed for flow %s", flow.pk)
        return render_template("bot_error")

    flow.state = WhatsAppFlow.State.DONE
    flow.context["appointment_reference"] = appointment.reference
    _save(flow)
    return render_template(
        "bot_booked", {"name": patient.name, "reference": appointment.reference}
    )


# -- state machine -----------------------------------------------------------

def handle_incoming(incoming) -> str:
    """Advance the flow for one inbound message and return the next prompt."""
    from apps.appointments.models import Patient
    from apps.appointments.services.booking import get_or_create_patient
    from apps.appointments.services.patient_messages import queue_welcome_message
    from apps.core.rls import rls_scope
    from apps.doctors.models import Doctor

    text = incoming.text or ""
    starts_flow = _is_start(text)
    clinic = resolve_clinic(incoming.sender_phone)
    if clinic is None:
        if starts_flow:
            logger.warning("no clinic resolved for WhatsApp sender %s", incoming.sender_phone)
            return render_template("bot_error")
        return ""

    with rls_scope(str(clinic.id)):
        flow = WhatsAppFlow.objects.filter(
            clinic=clinic, chat_id=incoming.chat_id
        ).first()

        if starts_flow:
            if flow is None:
                flow = WhatsAppFlow.objects.create(
                    clinic=clinic,
                    chat_id=incoming.chat_id,
                    sender_phone=incoming.sender_phone,
                )
            flow.state = WhatsAppFlow.State.MENU
            flow.context = {}
            _save(flow)
            return _menu(clinic)

        # Unrelated messages are still logged and shown in the back office, but
        # only an exact "Hi" starts a conversation with the assistant.
        if flow is None:
            return ""

        state = flow.state

        # -- main menu ----------------------------------------------------
        if state == WhatsAppFlow.State.MENU:
            choice = _choice(text)
            if choice in (1, 2):
                flow.context = {
                    "service": "Appointment" if choice == 1 else "Online consultation"
                }
                flow.state = WhatsAppFlow.State.NAME
                _save(flow)
                return render_template("bot_name")
            if choice == 3:
                return _info(clinic)
            if choice == 4:
                flow.state = WhatsAppFlow.State.HANDOFF
                _save(flow)
                return render_template("bot_handoff", {"clinic_name": clinic.name})
            return _menu(clinic, "Please reply with 1, 2, 3 or 4.")

        # -- collect name -------------------------------------------------
        if state == WhatsAppFlow.State.NAME:
            name = " ".join(text.split())[:200]
            if len(name) < 2:
                return render_template("bot_unknown", {"hint": "Please tell me your full name."})
            flow.context["name"] = name
            flow.state = WhatsAppFlow.State.PHONE
            _save(flow)
            return render_template("bot_phone", {"name": name})

        # -- collect phone, create the patient ----------------------------
        if state == WhatsAppFlow.State.PHONE:
            phone = _normalise(text)
            if not phone:
                return render_template(
                    "bot_unknown", {"hint": "Please send a valid phone number."}
                )
            patient, created = get_or_create_patient(
                clinic=clinic, phone=phone, name=flow.context.get("name", "")
            )
            if created:
                queue_welcome_message(patient)
            flow.context["patient_id"] = str(patient.id)
            flow.context["phone"] = phone
            _save(flow)
            _link_chat_to_patient(clinic, patient, incoming.chat_id)
            return _doctor_prompt(clinic, flow)

        # -- choose doctor ------------------------------------------------
        if state == WhatsAppFlow.State.DOCTOR:
            ids = flow.context.get("doctor_ids") or []
            selection = _choice(text)
            doctor = None
            if selection is not None and 1 <= selection <= len(ids):
                doctor = Doctor.objects.filter(pk=ids[selection - 1], clinic=clinic).first()
            if doctor is None:
                return _doctor_prompt(clinic, flow, "Please choose a number from the list.")
            flow.context["doctor_id"] = str(doctor.id)
            flow.context["doctor_name"] = doctor.name
            flow.state = WhatsAppFlow.State.DATE
            _save(flow)
            return _date_prompt(clinic)

        # -- choose date --------------------------------------------------
        if state == WhatsAppFlow.State.DATE:
            on_date = _parse_date(text, clinic)
            today = _local_today(clinic)
            if on_date is None or on_date < today or on_date > today + timedelta(days=30):
                return _date_prompt(
                    clinic, "Please use YYYY-MM-DD for a date from today onwards."
                )
            doctor = Doctor.objects.filter(
                pk=flow.context.get("doctor_id"), clinic=clinic
            ).first()
            if doctor is None:
                flow.state = WhatsAppFlow.State.MENU
                flow.context = {}
                _save(flow)
                return _menu(clinic, "Let's start again.")
            flow.context["date"] = on_date.isoformat()
            _save(flow)
            return _slot_prompt(clinic, doctor, on_date, flow)

        # -- choose slot --------------------------------------------------
        if state == WhatsAppFlow.State.SLOT:
            doctor = Doctor.objects.filter(
                pk=flow.context.get("doctor_id"), clinic=clinic
            ).first()
            if doctor is None or not flow.context.get("date"):
                flow.state = WhatsAppFlow.State.MENU
                flow.context = {}
                _save(flow)
                return _menu(clinic, "Let's start again.")
            on_date = date.fromisoformat(flow.context["date"])
            starts = flow.context.get("slot_starts") or []
            selection = _choice(text)
            chosen = None
            if selection is not None and 1 <= selection <= len(starts):
                chosen = starts[selection - 1]
            else:
                cleaned = (text or "").strip()
                chosen = next((s for s in starts if s and s[11:16] == cleaned), None)
            if chosen is None:
                return _slot_prompt(
                    clinic, doctor, on_date, flow, "Please choose a time from the list."
                )
            flow.context["slot_start"] = chosen
            flow.save(update_fields=["context", "updated_at"])
            service = flow.context.get("service", "Appointment")
            return _confirm_prompt(clinic, flow, doctor, datetime.fromisoformat(chosen), service)

        # -- confirm ------------------------------------------------------
        if state == WhatsAppFlow.State.CONFIRM:
            first = _first(text)
            if first in _NO_WORDS:
                flow.state = WhatsAppFlow.State.MENU
                flow.context = {}
                _save(flow)
                return render_template("bot_cancelled", {"options": MENU_OPTIONS})
            if first not in _YES_WORDS:
                return render_template("bot_unknown", {"hint": "Please reply YES or NO."})
            patient = Patient.objects.filter(
                pk=flow.context.get("patient_id"), clinic=clinic
            ).first()
            doctor = Doctor.objects.filter(
                pk=flow.context.get("doctor_id"), clinic=clinic
            ).first()
            if patient is None or doctor is None:
                flow.state = WhatsAppFlow.State.MENU
                flow.context = {}
                _save(flow)
                return _menu(clinic, "Let's start again.")
            return _book(clinic, flow, doctor, patient, flow.context.get("service", "Appointment"))

        # -- handed off or booked ----------------------------------------
        # The conversation is over; another automated message would only
        # arrive for a fresh, exact "Hi" from the patient.
        return ""
