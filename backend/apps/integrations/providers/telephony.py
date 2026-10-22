"""Telephony provider adapter.

The concrete provider (Exotel, Twilio, Smartflo, ...) is a deployment
decision (PRD 16). This adapter speaks a generic, HMAC-signed webhook
format and normalises call events. Twilio-style ``X-Twilio-Signature``
verification is supported out of the box because it is the most common
pattern among the Indian providers Sarvam supports.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from apps.integrations.providers.base import (
    ProviderEvent,
    verify_hmac_sha1,
    verify_hmac_sha256,
)

logger = logging.getLogger("apps.integrations.telephony")

#: Normalised internal event types.
CALL_INBOUND = "call.inbound"
CALL_ANSWERED = "call.answered"
CALL_COMPLETED = "call.completed"
CALL_FAILED = "call.failed"
CALL_NO_ANSWER = "call.no_answer"


class TelephonyAdapter:
    """Generic telephony webhook adapter."""

    provider_type = "telephony"

    def __init__(self, *, auth_token: str = "", signature_scheme: str = "sha256") -> None:
        self.auth_token = auth_token
        self.signature_scheme = signature_scheme

    def verify_webhook(self, request) -> bool:  # noqa: ANN001
        if not self.auth_token:
            logger.error("Telephony webhook received but no auth token is configured.")
            return False

        twilio_signature = request.headers.get("X-Twilio-Signature")
        if twilio_signature:
            params = {}
            if hasattr(request, "data"):
                params = dict(request.data.items())
            elif hasattr(request, "POST"):
                params = dict(request.POST.items())
            url = request.build_absolute_uri()
            return verify_hmac_sha1(url, params, twilio_signature, self.auth_token)

        generic = request.headers.get("X-Signature") or request.headers.get("X-Signature-256")
        if generic and self.signature_scheme == "sha256":
            return verify_hmac_sha256(request.body, generic, self.auth_token)
        if generic:
            expected = hmac.new(
                self.auth_token.encode(), request.body, hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected, generic.split("=", 1)[-1].strip())
        return False

    def parse_events(self, payload: dict[str, Any]) -> list[ProviderEvent]:
        if not isinstance(payload, dict):
            return []

        call_sid = (
            payload.get("CallSid")
            or payload.get("call_sid")
            or payload.get("call_id")
            or payload.get("id")
        )
        if not call_sid:
            logger.warning("Telephony webhook without a call identifier; ignoring.")
            return []

        status = str(
            payload.get("CallStatus")
            or payload.get("status")
            or payload.get("Status")
            or ""
        ).lower()

        event_type = {
            "initiated": CALL_INBOUND,
            "ringing": CALL_INBOUND,
            "answered": CALL_ANSWERED,
            "in-progress": CALL_ANSWERED,
            "completed": CALL_COMPLETED,
            "busy": CALL_FAILED,
            "failed": CALL_FAILED,
            "no-answer": CALL_NO_ANSWER,
            "canceled": CALL_FAILED,
        }.get(status, CALL_COMPLETED)

        to_number = str(payload.get("To") or payload.get("to") or "")
        from_number = str(payload.get("From") or payload.get("from") or "")

        return [
            ProviderEvent(
                provider_type=self.provider_type,
                provider_event_id=str(call_sid),
                event_type=event_type,
                payload=payload,
                clinic_hint=to_number or None,
            )
        ]

    @staticmethod
    def extract_duration(payload: dict[str, Any]) -> int:
        for key in ("Duration", "duration", "call_duration"):
            value = payload.get(key)
            if value is not None:
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    continue
        return 0
