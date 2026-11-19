"""WAHA REST API client.

All WhatsApp HTTP traffic lives here: views and domain services never build
WAHA URLs or handle its API key. Every call returns a :class:`WahaResult` so
callers can react to failures without catching library-specific exceptions,
while failures are still logged (never silently swallowed).

Verified against the installed WAHA 2026.10.1 source:

* ``POST /api/sendText``  body ``{"session": ..., "chatId": ..., "text": ...}``
* ``GET  /api/sessions/{session}``
* ``GET  /health``

Authentication is the ``X-Api-Key`` header.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger("apps.integrations.waha")


class WahaError(Exception):
    """Base class for WAHA client failures."""


class WahaConfigurationError(WahaError):
    """The backend is missing a required WAHA setting."""


class WahaConnectionError(WahaError):
    """WAHA could not be reached."""


class WahaHTTPError(WahaError):
    """WAHA answered with an error status."""


class WahaInvalidResponseError(WahaError):
    """WAHA answered with something that is not a JSON object."""


@dataclass(frozen=True)
class WahaResult:
    """Structured outcome of a WAHA API call.

    ``error`` is safe to persist/show internally: it never contains the API
    key, message text or a recipient identifier.
    """

    ok: bool
    data: dict[str, Any] | None = None
    error: str = ""
    status_code: int | None = None


def _api_key() -> str:
    key = getattr(settings, "WAHA_API_KEY", "")
    if not key:
        raise WahaConfigurationError("WAHA_API_KEY is not configured.")
    return key


def _request(method: str, path: str, *, payload: dict[str, Any] | None = None) -> WahaResult:
    """Perform one authenticated request and translate failures into a result."""
    try:
        api_key = _api_key()
    except WahaConfigurationError as exc:
        logger.error("WAHA request cannot be made: %s", exc)
        return WahaResult(ok=False, error=str(exc))

    url = f"{settings.WAHA_BASE_URL}{path}"
    timeout = getattr(settings, "WAHA_REQUEST_TIMEOUT_SECONDS", 10.0)
    try:
        response = requests.request(
            method,
            url,
            json=payload,
            headers={
                "X-Api-Key": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
    except requests.Timeout:
        logger.warning("WAHA request to %s timed out after %ss", path, timeout)
        return WahaResult(ok=False, error="WAHA request timed out.")
    except requests.RequestException:
        # Do not log the URL/query: they are not needed to diagnose a local
        # connection failure and could carry identifying data in future paths.
        logger.warning("WAHA request to %s failed (connection error)", path, exc_info=True)
        return WahaResult(ok=False, error="WAHA is unreachable.")

    if response.status_code >= 400:
        logger.warning("WAHA request to %s returned HTTP %s", path, response.status_code)
        return WahaResult(
            ok=False,
            error=f"WAHA API returned HTTP {response.status_code}.",
            status_code=response.status_code,
        )

    try:
        body = response.json()
    except ValueError:
        logger.warning("WAHA request to %s returned invalid JSON", path)
        return WahaResult(
            ok=False,
            error="WAHA returned an invalid response.",
            status_code=response.status_code,
        )
    if not isinstance(body, dict):
        logger.warning("WAHA request to %s returned an unexpected response type", path)
        return WahaResult(
            ok=False,
            error="WAHA returned an unexpected response.",
            status_code=response.status_code,
        )
    return WahaResult(ok=True, data=body, status_code=response.status_code)


def _validate_recipient(chat_id: str) -> str:
    """Return an error string for an unusable recipient, else an empty string."""
    if not isinstance(chat_id, str) or not chat_id.strip():
        return "A non-empty chat_id is required."
    recipient = chat_id.strip()
    if any(char.isspace() or ord(char) < 32 for char in recipient):
        return "chat_id contains invalid characters."
    if recipient.endswith("@g.us") or "@g.us" in recipient:
        return "Group messages are not supported."
    if len(recipient) > 255:
        return "chat_id is too long."
    return ""


def send_text_message(chat_id: str, text: str) -> WahaResult:
    """Send a plain text message to a WhatsApp chat through WAHA."""
    recipient_error = _validate_recipient(chat_id)
    if recipient_error:
        logger.warning("refusing WAHA send: invalid recipient (%s)", recipient_error)
        return WahaResult(ok=False, error=recipient_error)

    if not isinstance(text, str) or not text.strip():
        return WahaResult(ok=False, error="A non-empty text is required.")
    max_length = getattr(settings, "WAHA_MAX_TEXT_LENGTH", 4096)
    if len(text) > max_length:
        return WahaResult(ok=False, error=f"text exceeds {max_length} characters.")

    session = getattr(settings, "WAHA_SESSION", "")
    if not session:
        logger.error("WAHA_SESSION is not configured.")
        return WahaResult(ok=False, error="WAHA_SESSION is not configured.")

    return _request(
        "POST",
        "/api/sendText",
        payload={"session": session, "chatId": chat_id.strip(), "text": text.strip()},
    )


def get_session_status(session: str | None = None) -> WahaResult:
    """Return WAHA's view of a session (name, status, me, ...)."""
    session = session or getattr(settings, "WAHA_SESSION", "")
    if not session:
        return WahaResult(ok=False, error="WAHA_SESSION is not configured.")
    return _request("GET", f"/api/sessions/{session}")


def get_waha_health() -> WahaResult:
    """Return the WAHA server health check."""
    return _request("GET", "/health")
