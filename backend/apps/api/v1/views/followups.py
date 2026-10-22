"""Follow-up task endpoints."""
from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.api.v1.mixins import TenantScopedViewSet
from apps.api.v1.permissions import IsStaffMember
from apps.api.v1.serializers import (
    FollowUpTaskSerializer,
    FollowUpTaskUpdateSerializer,
    ResolveTaskSerializer,
)
from apps.conversations.models import FollowUpTask
from apps.conversations.services.followups import FollowUpService
from apps.core.audit import record_audit
from apps.core.constants import AuditAction


class FollowUpTaskViewSet(TenantScopedViewSet):
    """The clinic's follow-up queue."""

    model = FollowUpTask
    serializer_class = FollowUpTaskSerializer
    permission_classes = [IsStaffMember]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("patient", "assigned_to")
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("assigned_to"):
            queryset = queryset.filter(assigned_to_id=params["assigned_to"])
        if params.get("priority"):
            queryset = queryset.filter(priority=params["priority"])
        return queryset.order_by("status", "due_at")

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = FollowUpTaskUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        for field, value in data.items():
            setattr(instance, field, value)
        instance.save(
            update_fields=[
                *data.keys(),
                "updated_at",
            ]
        )
        record_audit(
            action=AuditAction.UPDATE,
            resource_type="follow_up_task",
            resource_id=instance.id,
            clinic_id=instance.clinic_id,
            actor=request.user,
            request=request,
            metadata={"status": instance.status},
        )
        return Response(FollowUpTaskSerializer(instance).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):  # noqa: ANN001
        task = self.get_object()
        serializer = ResolveTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = FollowUpService.resolve(
            task,
            resolution_reason=serializer.validated_data.get("resolution_reason", ""),
            notes=serializer.validated_data.get("notes", ""),
            actor=request.user,
        )
        record_audit(
            action=AuditAction.RESOLVE,
            resource_type="follow_up_task",
            resource_id=task.id,
            clinic_id=task.clinic_id,
            actor=request.user,
            request=request,
            metadata={"status": task.status},
        )
        return Response(FollowUpTaskSerializer(task).data)
