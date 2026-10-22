"""Conversation and call-log endpoints.

These are read-only operational views. The dashboard uses them to answer
"what happened on the phone?" without exposing transcripts: the models
carry *references* to retained content, not the content itself.
"""
from __future__ import annotations

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.v1.mixins import TenantScopedViewSet
from apps.api.v1.permissions import IsStaffMember
from apps.api.v1.serializers import CallLogSerializer, ConversationSerializer
from apps.conversations.models import CallLog, Conversation


class ConversationViewSet(TenantScopedViewSet):
    """Patient interactions across the voice and WhatsApp channels."""

    model = Conversation
    serializer_class = ConversationSerializer
    permission_classes = [IsStaffMember]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("patient")
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("channel"):
            queryset = queryset.filter(channel=params["channel"])
        if params.get("outcome"):
            queryset = queryset.filter(outcome=params["outcome"])
        return queryset.order_by("-created_at")

    http_method_names = ["get", "head", "options"]

    def retrieve(self, request, *args, **kwargs):  # noqa: ANN001
        conversation = self.get_object()
        messages = conversation.messages.order_by("created_at")
        return Response(
            {
                "conversation": ConversationSerializer(conversation).data,
                "messages": [
                    {
                        "id": str(message.id),
                        "direction": message.direction,
                        "message_type": message.message_type,
                        "excerpt": message.excerpt,
                        "created_at": message.created_at.isoformat(),
                    }
                    for message in messages
                ],
            }
        )


class CallLogViewSet(TenantScopedViewSet):
    """The operational record of phone calls."""

    model = CallLog
    serializer_class = CallLogSerializer
    permission_classes = [IsStaffMember]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("conversation")
        params = self.request.query_params
        if params.get("outcome"):
            queryset = queryset.filter(outcome=params["outcome"])
        if params.get("direction"):
            queryset = queryset.filter(direction=params["direction"])
        if params.get("from"):
            queryset = queryset.filter(created_at__gte=params["from"])
        if params.get("to"):
            queryset = queryset.filter(created_at__lte=params["to"])
        return queryset.order_by("-created_at")

    http_method_names = ["get", "head", "options"]
