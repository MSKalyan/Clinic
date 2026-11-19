"""WAHA webhook and authenticated internal messaging endpoints."""
from __future__ import annotations

import json
import logging
import uuid

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.v1.base import TenantAwareAPIView
from apps.api.v1.permissions import IsClinicMember
from apps.integrations.providers.registry import get_waha_adapter
from apps.integrations.services.waha import get_session_status, get_waha_health
from apps.integrations.services.waha_flow import process_webhook

logger = logging.getLogger("apps.api.waha")


@method_decorator(csrf_exempt, name="dispatch")
class WahaWebhookView(View):
    """Receives WAHA ``message`` events at ``/api/v1/webhooks/waha/``.

    CSRF is disabled deliberately: this endpoint is called by a server, not a
    browser. Authentication uses the WAHA shared secret (and body HMAC), not a
    Django session.
    """

    def post(self, request, *args, **kwargs):
        adapter = get_waha_adapter()
        if not adapter.verify_webhook(request):
            logger.warning("rejected WAHA webhook: authentication failed")
            return JsonResponse(
                {"error": {"code": "invalid_signature", "message": "Signature verification failed."}},
                status=403,
            )

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("WAHA webhook received an unreadable body")
            return JsonResponse(
                {"error": {"code": "invalid_payload", "message": "Malformed JSON payload."}},
                status=400,
            )

        summary = process_webhook(payload, adapter=adapter)
        return JsonResponse(summary, status=200)


class WahaSendSerializer(serializers.Serializer):
    conversation_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    chat_id = serializers.CharField(max_length=255, trim_whitespace=True, required=False)
    text = serializers.CharField(max_length=4096, trim_whitespace=True)
    idempotency_key = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("conversation_id") and not attrs.get("chat_id"):
            raise serializers.ValidationError("conversation_id or chat_id is required.")
        return attrs


class WahaSendMessageView(TenantAwareAPIView):
    """Staff-only endpoint for sending a WhatsApp text through WAHA.

    The message is recorded once with an idempotency key and delivered by a
    worker. Sending it inline made the dashboard hang for up to ten seconds
    whenever WAHA was slow.
    """

    permission_classes = (IsAuthenticated, IsClinicMember)

    def post(self, request, *args, **kwargs):
        from apps.conversations.models import Conversation
        from apps.conversations.services.notifications import NotificationService
        from apps.core.constants import Channel, ConsentPurpose
        from apps.core.exceptions import OptedOut, TenantAccessDenied

        serializer = WahaSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        clinic = getattr(request, "clinic", None)
        if clinic is None:
            raise TenantAccessDenied("No clinic context for this request.")

        conversation = None
        if data.get("conversation_id"):
            conversation = (
                Conversation.objects.filter(
                    pk=data["conversation_id"], clinic=clinic, channel=Channel.WHATSAPP
                )
                .select_related("patient")
                .first()
            )
            if conversation is None:
                raise serializers.ValidationError(
                    {"conversation_id": "That WhatsApp conversation was not found."}
                )
            chat_id = conversation.provider_conversation_id
            patient = conversation.patient
        else:
            chat_id = data["chat_id"]
            patient = None

        if not chat_id:
            raise serializers.ValidationError(
                {"conversation_id": "This conversation has no WhatsApp chat id."}
            )
        if patient is not None and not patient.prefers(Channel.WHATSAPP):
            raise OptedOut("This patient has opted out of WhatsApp messages.")

        key = data.get("idempotency_key") or f"staff-reply:{uuid.uuid4()}"
        log = NotificationService.send(
            clinic=clinic,
            patient=patient,
            channel=Channel.WHATSAPP,
            template_id="staff_reply",
            body=data["text"],
            purpose=ConsentPurpose.APPOINTMENT_TRANSACTIONAL,
            idempotency_key=key,
            payload={"chat_id": chat_id, "conversation_id": str(conversation.pk) if conversation else ""},
        )
        return Response(
            {
                "status": "queued" if log.delivery_status != "sent" else "sent",
                "idempotency_key": key,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class WahaStatusView(TenantAwareAPIView):
    """Read-only WAHA health/session information for local verification."""

    permission_classes = (IsAuthenticated, IsClinicMember)

    def get(self, request, *args, **kwargs):
        health = get_waha_health()
        session = get_session_status()
        return Response(
            {
                "health": {"ok": health.ok, "data": health.data, "error": health.error},
                "session": {"ok": session.ok, "data": session.data, "error": session.error},
            },
            status=status.HTTP_200_OK,
        )
