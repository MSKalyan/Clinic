"""Small shared utilities."""
from __future__ import annotations

import re

_PHONE_STRIP = re.compile(r"[^\d+]")

#: Default country code for the initial market.
DEFAULT_COUNTRY_CODE = "+91"


def normalise_phone(raw: str | None, *, default_country_code: str = DEFAULT_COUNTRY_CODE) -> str:
    """Normalise a phone number to E.164-ish form.

    Indian numbers are 10 digits; we prepend ``+91``. Numbers that already
    carry a ``+`` are preserved. Returns ``""`` for empty input.
    """
    if not raw:
        return ""
    value = _PHONE_STRIP.sub("", str(raw).strip())
    if not value:
        return ""
    if value.startswith("+"):
        return "+" + value[1:].lstrip("0") or "+"
    if value.startswith("00"):
        return "+" + value[2:].lstrip("0")
    digits = value.lstrip("0")
    if len(digits) == 10:
        return f"{default_country_code}{digits}"
    if len(digits) == 11 and digits.startswith("91"):
        return f"+{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return f"+{digits}" if digits else ""


def mask_phone(phone: str | None) -> str:
    """Mask a phone number for display: ``+9198******10``."""
    if not phone:
        return ""
    text = str(phone)
    if len(text) <= 5:
        return "*" * len(text)
    return f"{text[:3]}{'*' * (len(text) - 5)}{text[-2:]}"


def truncate(text: str | None, limit: int = 255) -> str:
    if not text:
        return ""
    return str(text)[:limit]
