"""Sarvam Voice Agents adapter.

Grounded in the public Sarvam Voice Agents documentation:

* the inbound-call webhook posts ``app_id``, ``deployment_id``,
  ``interaction_id``, ``user_phone_number``, ``agent_phone_number``,
  ``duration``, ``start_datetime``/``end_datetime``,
  ``final_agent_variables``/``output_agent_variables``,
  ``interaction_transcript`` and ``metadata``;
* ``interaction_id`` is the per-call identifier, so it is our deduplication
  and idempotency key;
* ``agent_phone_number`` is the inbound number the patient dialled, which is
  the *trusted routing metadata* that identifies the clinic;
* API tools are plain HTTP endpoints (one URL per tool) that can use bearer
  token auth and can receive call-context variables such as the interaction
  id, the caller identifier and the call length.

Reference: https://docs.sarvam.ai/voice-agents/introduction
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone
from typing import Any

from apps.integrations.providers.base import (
    ProviderEvent,
    verify_secret_token,
    webhook_path_secret,
)

logger = logging.getLogger("apps.integrations.sarvam")

SARVAM_APP_AUTHORING_BASE = "https://apps.sarvam.ai/api/app-authoring/v1"

#: Sarvam's published egress IPs -- allowlist these in the security group
#: or WAF that fronts the webhook endpoint.
SARVAM_EGRESS_IPS = ("4.213.167.70", "35.154.84.150")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


class SarvamVoiceAdapter:
    """Adapts Sarvam Voice Agents webhooks into internal events."""

    provider_type = "sarvam"
    channel = "voice"

    def __init__(self, *, webhook_secret: str = "", api_key: str = "") -> None:
        self.webhook_secret = webhook_secret
        self.api_key = api_key

    # -- authentication -------------------------------------------------
    def verify_webhook(self, request) -> bool:  # noqa: ANN001
        """Authenticate an inbound Sarvam webhook.

        Sarvam's ``WebhookConfig`` carries only a URL and free-form metadata,
        so the shared secret is carried in the URL path and checked here.
        An ``X-API-Key`` header is accepted as well when configured.
        """
        if self.api_key:
            provided = request.headers.get("X-API-Key")
            if provided and verify_secret_token(provided, self.api_key):
                return True
        if not self.webhook_secret:
            # No secret configured -> the endpoint must not be reachable.
            logger.error("Sarvam webhook received but no webhook secret is configured.")
            return False
        secret_in_path = webhook_path_secret(request)
        if secret_in_path and verify_secret_token(secret_in_path, self.webhook_secret):
            return True
        header_secret = request.headers.get("X-Webhook-Secret")
        return bool(header_secret) and verify_secret_token(header_secret, self.webhook_secret)

    # -- normalisation --------------------------------------------------
    def parse_events(self, payload: dict[str, Any]) -> list[ProviderEvent]:
        """Convert a Sarvam deployment webhook payload into internal events."""
        if not isinstance(payload, dict):
            return []

        interaction_id = payload.get("interaction_id")
        if not interaction_id:
            logger.warning("Sarvam webhook without interaction_id; ignoring.")
            return []

        agent_phone = payload.get("agent_phone_number")
        event_type = "call.completed"
        return [
            ProviderEvent(
                provider_type=self.provider_type,
                provider_event_id=str(interaction_id),
                event_type=event_type,
                payload=payload,
                clinic_hint=agent_phone,
                occurred_at=_parse_dt(payload.get("end_datetime")),
            )
        ]

    @staticmethod
    def extract_outcome(payload: dict[str, Any]) -> dict[str, Any]:
        """Pull the agent-reported outcome out of a call payload.

        The variables are a *hint* from the agent. Authoritative state (what
        was actually booked) always comes from our own tables.
        """
        variables = {}
        for key in ("final_agent_variables", "output_agent_variables"):
            value = payload.get(key)
            if isinstance(value, dict):
                variables.update(value)
        return {
            "call_outcome": variables.get("call_outcome", ""),
            "follow_up_required": bool(variables.get("follow_up_required", False)),
            "variables": variables,
        }

    @staticmethod
    def extract_transcript(payload: dict[str, Any]) -> list[dict[str, str]]:
        transcript = payload.get("interaction_transcript")
        if not isinstance(transcript, list):
            return []
        turns: list[dict[str, str]] = []
        for turn in transcript:
            if not isinstance(turn, dict):
                continue
            turns.append(
                {
                    "role": str(turn.get("role", "")),
                    "text": str(turn.get("en_text") or turn.get("indic_text") or ""),
                }
            )
        return turns

    # -- outbound (campaigns / provisioning) ----------------------------
    def create_inbound_deployment(
        self,
        *,
        org_id: str,
        workspace_id: str,
        name: str,
        app_id: str,
        app_version: int,
        connection_id: str,
        agent_phone_number: str,
        webhook_url: str,
        inbound_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an inbound deployment (PRD 7.1 / 16)."""
        import requests

        url = (
            f"{SARVAM_APP_AUTHORING_BASE}/orgs/{org_id}/workspaces/{workspace_id}/deployments"
        )
        body: dict[str, Any] = {
            "name": name,
            "app_id": app_id,
            "app_version": app_version,
            "connection_configs": [
                {"connection_id": connection_id, "agent_phone_number": agent_phone_number}
            ],
            "webhook_config": {"url": webhook_url},
        }
        if inbound_config:
            body["inbound_config"] = inbound_config

        response = requests.post(
            url,
            json=body,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
