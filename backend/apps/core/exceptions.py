"""Domain exceptions and a consistent API error envelope."""
from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(APIException):
    """Base class for expected, business-level failures.

    These are *not* bugs: they represent a normal outcome that the caller
    (dashboard, AI tool, patient-facing flow) must handle gracefully.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "domain_error"
    default_detail = "The request could not be completed."

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code or self.default_code
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        super().__init__(detail or self.default_detail, code=self.code)


class SlotUnavailable(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "slot_unavailable"
    default_detail = "That appointment slot is no longer available."


class TenantAccessDenied(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "tenant_access_denied"
    default_detail = "You do not have access to this clinic's resources."


class ClinicSuspended(DomainError):
    status_code = status.HTTP_423_LOCKED
    default_code = "clinic_suspended"
    default_detail = "This clinic is currently suspended."


class InvalidTransition(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "invalid_transition"
    default_detail = "That status transition is not allowed."


class ConsentRequired(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "consent_required"
    default_detail = "The patient has not consented to this communication."


class OptedOut(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "opted_out"
    default_detail = "The patient has opted out of this channel."


class EmergencyDetected(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "emergency_detected"
    default_detail = "This request looks like a medical emergency."


class StaleStatus(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "stale_status"
    default_detail = "The recorded status is too old to rely on."


class ProviderError(DomainError):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "provider_error"
    default_detail = "The communication provider could not complete the request."


def flatten_errors(value: Any) -> list[str]:
    """Turn DRF's nested error structure into a list of plain sentences.

    DRF hands back ``{"slug": [ErrorDetail("Enter a valid slug...")]}``.
    Rendering that directly produces
    ``slug: [ErrorDetail(string='Enter a valid slug...', code='invalid')]``
    -- a Python repr leaking into a user-facing message. The frontend
    shows this string in an error banner, so it has to read like a
    sentence a person can act on.
    """
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            for message in flatten_errors(item):
                if key in {"non_field_errors", "detail"}:
                    parts.append(message)
                else:
                    parts.append(f"{key}: {message}")
        return parts
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            parts.extend(flatten_errors(item))
        return parts
    return [str(value)]


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Render every error with the same envelope.

    ``{"error": {"code", "message", "details", "request_id"}}``
    """
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    request = context.get("request")
    request_id = getattr(request, "request_id", "")

    data = response.data
    details: dict[str, Any] = {}
    code = getattr(exc, "default_code", None) or getattr(exc, "code", None) or "error"
    message = ""

    if isinstance(exc, DomainError):
        code = exc.code
        message = str(exc.detail)
        details = exc.details
    elif isinstance(data, dict) and "detail" in data:
        message = str(data["detail"])
        code = getattr(exc, "default_code", code)
    elif isinstance(data, list) and data:
        message = "; ".join(flatten_errors(data))
        details = {"errors": data}
    elif isinstance(data, dict):
        message = "; ".join(flatten_errors(data))
        details = {"fields": data}
    else:
        message = str(data)

    if response.status_code == status.HTTP_404_NOT_FOUND:
        code = "not_found"
    elif response.status_code == status.HTTP_403_FORBIDDEN:
        code = code or "forbidden"

    response.data = {
        "error": {
            "code": str(code),
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }
    return response
