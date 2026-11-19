"""Patient-facing message templates.

Every outbound text the clinic sends goes through this registry. Templates are
ordinary Python format strings kept in one place so wording can be changed in
settings without touching a webhook or a service. Each template documents the
context keys it accepts; unknown keys are rendered as an empty string instead
of breaking a message.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger("apps.conversations.templates")

#: (code, text) pairs. ``MESSAGE_TEMPLATES`` in Django settings overrides any
#: of these, so deployments can reword messages without a code change.
DEFAULT_TEMPLATES: dict[str, str] = {
    "welcome": (
        "Hi {patient_name}, welcome to {clinic_name}! "
        "We have saved your details and you can reply to this message any time "
        "if you need help with appointments or have a question for our team."
    ),
    "booked": (
        "Hi {patient_name}, your appointment at {clinic_name} is confirmed.\n"
        "Reference: {reference}\n"
        "Doctor: {doctor_name}\n"
        "When: {when} ({timezone})\n"
        "Reply to this message if you need to reschedule or cancel.\n"
        "Thank you."
    ),
    "rescheduled": (
        "Hi {patient_name}, your appointment at {clinic_name} has been rescheduled.\n"
        "Reference: {reference}\n"
        "Doctor: {doctor_name}\n"
        "New time: {when} ({timezone})\n"
        "Reply to this message if you need to make another change.\n"
        "Thank you."
    ),
    "cancelled": (
        "Hi {patient_name}, your appointment at {clinic_name} ({reference}) "
        "with {doctor_name} scheduled for {when} has been cancelled. "
        "Reply to this message to book a new time.\n"
        "Thank you."
    ),
    "reminder": (
        "Reminder: your appointment with {doctor_name} at {clinic_name} is on "
        "{when} ({timezone}). Reference: {reference}. Reply here if you need to "
        "reschedule or cancel."
    ),
    "auto_reply": (
        "Hello! Welcome to {clinic_name}. Thank you for messaging us - a member "
        "of our team will read your message and reply here shortly."
    ),
    # -- WhatsApp booking assistant -------------------------------------
    "bot_menu": (
        "Hi! Welcome to {clinic_name}.\n"
        "Specialities: {specialities}\n"
        "Clinic hours: {hours}\n"
        "Next available: {availability}\n\n"
        "How can we help?\n{options}\n"
        "Reply with the number."
    ),
    "bot_info": (
        "{clinic_name}\nSpecialities: {specialities}\nDoctors:\n{doctors}\n"
        "Hours: {hours}\n\n{options}"
    ),
    "bot_doctors": "Choose a doctor:\n{doctors}\n\nReply with the number.",
    "bot_date": (
        "Which date would you like? Reply with YYYY-MM-DD.\n{hint}"
    ),
    "bot_slots": (
        "Free times with {doctor_name} on {date}:\n{slots}\n\n"
        "Reply with the number or the time."
    ),
    "bot_name": "What is your full name?",
    "bot_phone": "Thanks, {name}. What is your phone number? (e.g. +919876543210)",
    "bot_confirm": (
        "Please confirm your booking:\n"
        "Name: {name}\nPhone: {phone}\nService: {service}\n"
        "Doctor: {doctor_name}\nWhen: {when} ({timezone})\n\n"
        "Reply YES to confirm or NO to start again."
    ),
    "bot_booked": (
        "Booked, {name}! Reference: {reference}. "
        "Your appointment details have been sent to this number. "
        "Reply Hi any time."
    ),
    "bot_cancelled": "No problem - nothing was booked. How can we help?\n{options}",
    "bot_handoff": (
        "I have noted that you would like to speak to our team. A member of "
        "{clinic_name} will message you here shortly. Reply Hi to book instead."
    ),
    "bot_unknown": "Sorry, I did not catch that. {hint}",
    "bot_error": (
        "Sorry, something went wrong just now. Please send Hi to try again."
    ),
}


def templates() -> dict[str, str]:
    """Return the effective template registry for this deployment."""
    merged = dict(DEFAULT_TEMPLATES)
    # Legacy appointment overrides remain supported.
    legacy = getattr(settings, "WAHA_APPOINTMENT_MESSAGES", {}) or {}
    for code in ("booked", "rescheduled", "cancelled"):
        if legacy.get(code):
            merged[code] = str(legacy[code])
    configured = getattr(settings, "MESSAGE_TEMPLATES", {}) or {}
    merged.update({str(code): str(text) for code, text in configured.items() if text})
    return merged


class _Context(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def render_template(code: str, context: dict[str, Any] | None = None) -> str:
    """Render one registered template, falling back to the default on error.

    A bad deployment override must never stop a patient message: log it and
    use the built-in wording instead.
    """
    registry = templates()
    template = registry.get(code) or DEFAULT_TEMPLATES.get(code)
    if not template:
        logger.warning("unknown message template %s", code)
        return ""
    try:
        text = template.format_map(_Context(context or {})).strip()
    except (KeyError, IndexError, ValueError, AttributeError):
        logger.warning("invalid message template %s; using the default", code)
        text = DEFAULT_TEMPLATES.get(code, "").format_map(_Context(context or {})).strip()
    limit = getattr(settings, "WAHA_MAX_TEXT_LENGTH", 4096)
    return text[:limit]


def rendered(code: str, **context: Any) -> str:
    """Convenience wrapper for call sites that prefer keyword arguments."""
    return render_template(code, context)
