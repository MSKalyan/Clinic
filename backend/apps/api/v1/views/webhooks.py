"""Provider webhook endpoints.

Every webhook:

1. verifies the provider's signature (or shared secret);
2. normalises the payload into internal events;
3. deduplicates on the provider event id;
4. answers with a small acknowledgement.
"""
from __future__ import annotations

import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views import View

from apps.integrations.providers.base import webhook_path_secret
from apps.integrations.providers.registry import get_provider_for_webhook
from apps.integrations.services.webhooks import ingest_events

logger = logging.getLogger("apps.api.webhooks")


class BaseWebhookView(View):
    """Shared plumbing for provider webhooks."""

    provider = ""
    #: Whether the provider signs the body (vs. using a URL secret).
    requires_signature = True

    def dispatch(self, request, *args, **kwargs):
        """Reject a URL whose provider segment does not match this endpoint."""
        url_provider = kwargs.get("provider") or ""
        if url_provider and url_provider != self.provider:
            return JsonResponse(
                {
                    "error": {
                        "code": "unknown_provider",
                        "message": "This endpoint does not handle that provider.",
                    }
                },
                status=404,
            )
        return super().dispatch(request, *args, **kwargs)

    def get_secret(self, request) -> str:  # noqa: ANN001
        """The *candidate* secret carried by the request.

        This is only ever compared against the secret we hold; it is never
        used as the expected value.
        """
        secret = request.headers.get("X-Webhook-Secret", "")
        if secret:
            return secret
        return webhook_path_secret(request)

    def get_adapter(self, request):  # noqa: ANN001
        """Build the adapter around the secret *we* configured."""
        return get_provider_for_webhook(self.provider)

    def verify(self, request, adapter) -> bool:  # noqa: ANN001
        return adapter.verify_webhook(request)

    def parse_body(self, request) -> dict:  # noqa: ANN001
        try:
            return json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("%s webhook received an unreadable body", self.provider)
            return {}


class VoiceWebhookView(BaseWebhookView):
    """Inbound voice agent call events (Sarvam)."""

    provider = "sarvam"

    def post(self, request, *args, **kwargs):  # noqa: ANN001
        adapter = self.get_adapter(request)
        if not self.verify(request, adapter):
            logger.warning("rejected %s webhook: signature mismatch", self.provider)
            return JsonResponse(
                {"error": {"code": "invalid_signature", "message": "Signature verification failed."}},
                status=403,
            )
        payload = self.parse_body(request)
        events = adapter.parse_events(payload)
        summary = ingest_events(provider_type=self.provider, events=events)
        return JsonResponse(summary, status=200)


class WhatsAppWebhookView(BaseWebhookView):
    """WhatsApp Business Cloud API webhooks."""

    provider = "whatsapp"

    def get(self, request, *args, **kwargs):  # noqa: ANN001
        """Meta's subscription verification handshake."""
        from django.conf import settings

        params = request.GET
        if params.get("hub.mode") == "subscribe":
            token = params.get("hub.verify_token", "")
            expected = (
                request.headers.get("X-Webhook-Secret", "")
                or settings.WHATSAPP_VERIFY_TOKEN
                or settings.WHATSAPP_APP_SECRET
            )
            if not expected or token != expected:
                return HttpResponse(status=403)
            return HttpResponse(params.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponse(status=200)

    def post(self, request, *args, **kwargs):  # noqa: ANN001
        adapter = self.get_adapter(request)
        if not self.verify(request, adapter):
            logger.warning("rejected %s webhook: signature mismatch", self.provider)
            return JsonResponse(
                {"error": {"code": "invalid_signature", "message": "Signature verification failed."}},
                status=403,
            )
        payload = self.parse_body(request)
        events = adapter.parse_events(payload)
        summary = ingest_events(provider_type=self.provider, events=events)
        return JsonResponse(summary, status=200)


class TelephonyWebhookView(BaseWebhookView):
    """Telephony provider call events."""

    provider = "telephony"

    def post(self, request, *args, **kwargs):  # noqa: ANN001
        adapter = self.get_adapter(request)
        if not self.verify(request, adapter):
            logger.warning("rejected %s webhook: signature mismatch", self.provider)
            return JsonResponse(
                {"error": {"code": "invalid_signature", "message": "Signature verification failed."}},
                status=403,
            )
        payload = self.parse_body(request)
        events = adapter.parse_events(payload)
        summary = ingest_events(provider_type=self.provider, events=events)
        return JsonResponse(summary, status=200)
