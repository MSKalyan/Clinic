"""Safety helpers.

The assistant is administrative, not clinical. It must never diagnose,
prescribe or give treatment advice, and it must recognise language that
signals an emergency and route it to the clinic's safety policy instead of
routine booking logic (PRD 4.7 / 12.5).
"""
from __future__ import annotations

import re

_SAFETY_RESPONSE = (
    "This sounds like a medical emergency. Please call 112 immediately, or go to the "
    "nearest emergency department. I am an automated assistant and cannot help with "
    "medical emergencies."
)


def detect_emergency(text: str, keywords: list[str] | None = None) -> bool:
    """Return True when the text matches a configured emergency phrase."""
    if not text:
        return False
    lowered = text.lower()
    for keyword in keywords or []:
        if keyword and keyword.lower() in lowered:
            return True
    return False


def strip_punctuation(text: str) -> str:
    return re.sub(r"[^\w\s]", " ", text or "").lower()


def safety_response() -> str:
    return _SAFETY_RESPONSE


def contains_clinical_request(text: str) -> bool:
    """Detect a request for a diagnosis or treatment recommendation."""
    phrases = (
        "diagnose",
        "diagnosis",
        "prescribe",
        "prescription",
        "what medicine",
        "which tablet",
        "dosage",
        "is it safe to take",
        "symptoms of",
        "i have fever",
        "i have chest",
    )
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in phrases)
