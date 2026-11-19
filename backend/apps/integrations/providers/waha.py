"""WAHA webhook adapter.

Converts the installed WAHA version's webhook envelope into the small set of
fields this integration needs, and authenticates the callback before any of
it is read.

Envelope (WAHA 2026.10.1)::

    {
      "id": "evt_01...",          # event id, not the message id
      "timestamp": 1763200000000, # ms
      "event": "message",
      "session": "session_01",
      "payload": {
        "id": "false_1555...@c.us_ABCD",
        "timestamp": 1763200000,  # seconds
        "from": "1555...@c.us",
        "to": "1555...@c.us",
        "fromMe": false,
        "body": "Hi, I want to know about your clinic.",
        "hasMedia": false
      }
    }

Reference: the WAHA ``WAHAWebhook`` / ``WAMessage`` structures in the local
WAHA source tree.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from apps.core.exceptions import ProviderError
from apps.integrations.providers.base import ProviderEvent, verify_secret_token

logger = logging.getLogger("apps.integrations.waha.adapter")

#: Only this event represents an incoming message. ``message.any`` also
#: includes messages sent by our own account and is deliberately not used.
INCOMING_EVENT = "message"
GROUP_SUFFIX = "@g.us"


@dataclass(frozen=True)
class IncomingWahaMessage:
    """The normalised fields extracted from an inbound WAHA webhook."""

    session: str
    message_id: str
    sender_id: str
    sender_phone: str
    text: str
    timestamp: datetime | None
    chat_id: str


class WahaAdapter:
    """Authenticates and normalises WAHA webhooks."""

    provider_type = "waha"
    channel = "whatsapp"

    def __init__(self, *, webhook_secret: str = "", hmac_key: str = "", session: str = "") -> None:
        self.webhook_secret = webhook_secret
        self.hmac_key = hmac_key
        self.session = session

    # -- authentication -------------------------------------------------
    def verify_webhook(self, request) -> bool:
        """Check the shared secret and, when configured, the body HMAC.

        WAHA sends the secret as a configurable custom header and signs the
        raw body with HMAC-SHA512 when ``WHATSAPP_HOOK_HMAC_KEY`` is set.
        """
        if not self.webhook_secret:
            logger.error("WAHA webhook received but no webhook secret is configured.")
            return False

        candidate = request.headers.get("X-Webhook-Secret", "")
        if not candidate:
            from apps.integrations.providers.base import webhook_path_secret

            candidate = webhook_path_secret(request)
        if not verify_secret_token(candidate, self.webhook_secret):
            return False

        if self.hmac_key:
            signature = request.headers.get("X-Webhook-Hmac", "")
            algorithm = request.headers.get("X-Webhook-Hmac-Algorithm", "sha512")
            if algorithm.lower() != "sha512" or not signature:
                return False
            expected = hmac.new(
                self.hmac_key.encode(), request.body, hashlib.sha512
            ).hexdigest()
            if not hmac.compare_digest(expected, signature.strip().lower()):
                return False

        return True

    # -- normalisation --------------------------------------------------
    def parse_incoming(self, payload: dict[str, Any]) -> IncomingWahaMessage | None:
        """Return an inbound text message, or ``None`` for any event to ignore.

        Status updates, acknowledgements, reactions, outgoing messages and
        group messages all return ``None``.
        """
        if not isinstance(payload, dict):
            return None
        if payload.get("event") != INCOMING_EVENT:
            return None

        session = str(payload.get("session") or "")
        if self.session and session and session != self.session:
            logger.info("ignoring WAHA event from session %r (expected %r)", session, self.session)
            return None

        message = payload.get("payload")
        if not isinstance(message, dict):
            return None

        if message.get("fromMe") is True:
            return None
        if message.get("hasMedia") is True:
            return None

        chat_id = str(message.get("from") or "")
        if not chat_id or self._is_group(message):
            return None

        message_id = str(message.get("id") or "")
        if not message_id:
            return None

        text = message.get("body")
        if not isinstance(text, str) or not text.strip():
            # WAHA also exposes a dict-shaped `text` in some payloads.
            nested = message.get("text")
            if isinstance(nested, dict):
                text = nested.get("body")
            elif isinstance(nested, str):
                text = nested
        if not isinstance(text, str) or not text.strip():
            return None

        return IncomingWahaMessage(
            session=session,
            message_id=message_id,
            sender_id=chat_id,
            sender_phone=phone_from_chat_id(chat_id),
            text=text,
            timestamp=_parse_timestamp(message.get("timestamp") or payload.get("timestamp")),
            chat_id=chat_id,
        )

    @staticmethod
    def _is_group(message: dict[str, Any]) -> bool:
        return any(
            GROUP_SUFFIX in str(message.get(field) or "")
            for field in ("from", "to", "participant", "author")
        )

    # -- outbound messaging ---------------------------------------------
    def send_message(
        self,
        *,
        clinic=None,
        recipient_phone: str,
        template_id: str = "",
        body: str = "",
        appointment=None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Send a text through WAHA, satisfying the ``MessagingProvider`` protocol.

        WAHA addresses chats by ``<digits>@c.us``, while the clinic stores
        E.164-ish numbers. Converting here keeps the difference out of the
        domain layer.
        """
        from apps.integrations.services.waha import send_text_message

        chat_id = phone_to_chat_id(recipient_phone)
        if not chat_id:
            raise ProviderError("The patient has no usable WhatsApp number.")
        if not body or not body.strip():
            raise ProviderError("No message text was provided.")

        result = send_text_message(chat_id, body)
        if not result.ok:
            raise ProviderError(result.error or "WAHA could not deliver the message.")
        return str((result.data or {}).get("id") or "")

    # -- provider protocol ----------------------------------------------
    def parse_events(self, payload: dict[str, Any]) -> list[ProviderEvent]:
        """Normalise an event for the shared provider pipeline.

        Kept so the adapter follows the same shape as the other providers in
        ``apps.integrations.providers``.
        """
        incoming = self.parse_incoming(payload)
        if incoming is None:
            return []
        return [
            ProviderEvent(
                provider_type=self.provider_type,
                provider_event_id=incoming.message_id,
                event_type="message.received",
                payload={
                    "message": {
                        "id": incoming.message_id,
                        "from": incoming.sender_id,
                        "text": {"body": incoming.text},
                        "timestamp": incoming.timestamp,
                    }
                },
                clinic_hint=incoming.sender_phone,
                occurred_at=incoming.timestamp,
            )
        ]


def phone_to_chat_id(phone: str) -> str:
    """Return the WAHA WhatsApp chat id for an E.164-ish phone number.

    ``+91 98765 43210`` -> ``919876543210@c.us``. An empty string means the
    number cannot be addressed on WhatsApp and the caller must not send.
    """
    digits = "".join(char for char in str(phone or "") if char.isdigit())
    return f"{digits}@c.us" if digits else ""


def phone_from_chat_id(chat_id: str) -> str:
    """Best-effort E.164-ish phone number from a WhatsApp chat id.

    ``15551234567@c.us`` -> ``+15551234567``; WhatsApp LID/other suffixes
    yield an empty string rather than a misleading value.
    """
    if not chat_id or "@" not in chat_id:
        return ""
    local = chat_id.split("@", 1)[0].split(":", 1)[0]
    digits = "".join(char for char in local if char.isdigit())
    if not digits or "@c.us" not in chat_id:
        return ""
    return f"+{digits}"


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    # WAHA message timestamps are seconds; the outer event timestamp is ms.
    if number > 100_000_000_000:
        number /= 1000
    try:
        return datetime.fromtimestamp(number, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
