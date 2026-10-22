"""WhatsApp Business Cloud API adapter.

Handles the two things that matter for correctness:

* **Verification** -- inbound webhooks are authenticated with the
  ``X-Hub-Signature-256`` HMAC over the *raw* request body.
* **Normalisation** -- the nested ``entry/changes/value`` envelope is
  flattened into internal events, each carrying the provider message id so
  duplicate deliveries are ignored.

Reference: https://developers.facebook.com/docs/whatsapp/cloud-api/
"""
from __future__ import annotations

import logging
from typing import Any

from apps.integrations.providers.base import ProviderEvent, verify_hmac_sha256

logger = logging.getLogger("apps.integrations.whatsapp")

#: Delivery status values that mean the message reached the patient.
DELIVERED_STATUSES = {"delivered", "read", "sent", "sent_to_carrier"}


class WhatsAppCloudAdapter:
    """Adapts WhatsApp Cloud API webhooks into internal events."""

    provider_type = "whatsapp"
    channel = "whatsapp"

    def __init__(self, *, app_secret: str = "", access_token: str = "", phone_number_id: str = "") -> None:
        self.app_secret = app_secret
        self.access_token = access_token
        self.phone_number_id = phone_number_id

    # -- authentication -------------------------------------------------
    def verify_webhook(self, request) -> bool:  # noqa: ANN001
        if not self.app_secret:
            logger.error("WhatsApp webhook received but no app secret is configured.")
            return False
        signature = request.headers.get("X-Hub-Signature-256")
        return verify_hmac_sha256(request.body, signature or "", self.app_secret)

    @staticmethod
    def verification_challenge(request) -> str | None:  # noqa: ANN001
        """Answer Meta's webhook subscription handshake."""
        params = request.query_params
        if params.get("hub.mode") == "subscribe":
            return params.get("hub.challenge")
        return None

    # -- normalisation --------------------------------------------------
    def parse_events(self, payload: dict[str, Any]) -> list[ProviderEvent]:
        events: list[ProviderEvent] = []
        if not isinstance(payload, dict):
            return events

        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value", {}) or {}
                metadata = value.get("metadata", {}) or {}
                phone_number_id = metadata.get("phone_number_id", "")

                for message in value.get("messages", []) or []:
                    message_id = message.get("id")
                    if not message_id:
                        continue
                    events.append(
                        ProviderEvent(
                            provider_type=self.provider_type,
                            provider_event_id=str(message_id),
                            event_type="message.received",
                            payload={
                                "message": message,
                                "metadata": metadata,
                                "raw": value,
                            },
                            clinic_hint=phone_number_id,
                        )
                    )

                for status in value.get("statuses", []) or []:
                    status_id = status.get("id")
                    if not status_id:
                        continue
                    events.append(
                        ProviderEvent(
                            provider_type=self.provider_type,
                            provider_event_id=str(status_id),
                            event_type="message.status",
                            payload={
                                "status": status,
                                "metadata": metadata,
                                "raw": value,
                            },
                            clinic_hint=phone_number_id,
                        )
                    )
        return events

    @staticmethod
    def extract_text(payload: dict[str, Any]) -> str:
        message = payload.get("message", {}) or {}
        text = message.get("text", {}) or {}
        body = text.get("body")
        if isinstance(body, dict):
            return str(body.get("body", ""))
        return str(body or "")

    @staticmethod
    def extract_sender(payload: dict[str, Any]) -> str:
        message = payload.get("message", {}) or {}
        return str(message.get("from", "") or "")

    # -- outbound -------------------------------------------------------
    def send_message(
        self,
        *,
        clinic,
        recipient_phone: str,
        template_id: str,
        body: str = "",
        appointment=None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Send a message and return the provider message id."""
        import requests
        from django.conf import settings

        payload = payload or {}
        to = recipient_phone
        if template_id and template_id != "freeform":
            data = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_id,
                    "language": {"code": payload.get("language", "en")},
                },
            }
            if payload.get("parameters"):
                data["template"]["components"] = [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(param)}
                            for param in payload["parameters"]
                        ],
                    }
                ]
        else:
            data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": body},
            }

        url = f"{settings.WHATSAPP_GRAPH_URL}/{self.phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        response = requests.post(
            url,
            json=data,
            headers={
                "Authorization": f"Bearer {self.access_token or settings.WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"WhatsApp send failed ({response.status_code}): {response.text[:400]}"
            )
        data = response.json()
        return str((data.get("messages") or [{}])[0].get("id", ""))

    def send_template(
        self,
        *,
        recipient_phone: str,
        template_name: str,
        language_code: str = "en",
        parameters: list[str] | None = None,
    ) -> str:
        """Send an approved template (PRD 5.5 WAP-10)."""
        import requests
        from django.conf import settings

        data: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": recipient_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if parameters:
            data["template"]["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in parameters],
                }
            ]
        url = f"{settings.WHATSAPP_GRAPH_URL}/{self.phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        response = requests.post(
            url,
            json=data,
            headers={
                "Authorization": f"Bearer {self.access_token or settings.WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"WhatsApp template send failed ({response.status_code}): {response.text[:400]}"
            )
        return str((response.json().get("messages") or [{}])[0].get("id", ""))
