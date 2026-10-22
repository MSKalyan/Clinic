"""Clinic, membership and settings endpoints."""
from __future__ import annotations

from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import ClinicMembership
from apps.api.v1.base import TenantAwareModelViewSet
from apps.api.v1.mixins import TenantScopedViewSet
from apps.api.v1.permissions import (
    IsClinicAdmin,
    IsClinicMember,
    IsPlatformAdmin,
)
from apps.api.v1.serializers import (
    ClinicAgentConfigSerializer,
    ClinicChannelNumberSerializer,
    ClinicSerializer,
    ClinicSettingsSerializer,
    MembershipCreateSerializer,
    MembershipSerializer,
    ProviderConnectionSerializer,
)
from apps.core.audit import record_audit
from apps.core.constants import AuditAction, ClinicStatus
from apps.core.secrets import (
    GROUP_LABELS,
    GROUP_ORDER,
    SCOPE_CLINIC,
    clear_clinic_value,
    describe as describe_configuration,
    get_spec as get_key_spec,
    set_clinic_value,
)
from apps.tenancy.models import (
    Clinic,
    ClinicAgentConfig,
    ClinicChannelNumber,
    ClinicSettings,
    ProviderConnection,
)


class ClinicViewSet(TenantAwareModelViewSet):
    """A user sees the clinics they belong to."""

    serializer_class = ClinicSerializer

    def get_queryset(self):
        user = self.request.user
        if getattr(user, "is_platform_admin", False):
            return Clinic.objects.all()
        return Clinic.objects.filter(
            memberships__user=user, memberships__status="active"
        ).distinct()

    def get_permissions(self):
        if self.action in {"create"}:
            return [IsAuthenticated()]
        if self.action in {"update", "partial_update", "destroy"}:
            return [IsAuthenticated(), IsClinicAdmin()]
        return [IsAuthenticated()]

    def perform_create(self, serializer) -> None:
        from apps.accounts.models import User

        from apps.core.rls import rls_scope

        clinic = serializer.save(status=ClinicStatus.ONBOARDING)
        User.objects.get_or_create(
            email=self.request.user.email,
            defaults={"username": self.request.user.email},
        )
        # The caller has no membership of this clinic yet, so the request's
        # tenant scope is still whatever it was -- usually empty. The audit
        # row carries the new clinic's id, and the row-level security policy
        # would reject it. Scope the session to the clinic that was just
        # created for the duration of the writes that belong to it.
        with rls_scope(str(clinic.id)):
            ClinicMembership.objects.create(
                clinic=clinic,
                user=self.request.user,
                role="clinic_admin",
                status="active",
            )
            record_audit(
                action=AuditAction.CREATE,
                resource_type="clinic",
                resource_id=clinic.id,
                clinic_id=clinic.id,
                actor=self.request.user,
                request=self.request,
            )

    @action(detail=True, methods=["get", "patch"], url_path="settings")
    def clinic_settings(self, request, pk=None):  # noqa: ANN001
        """The clinic's operating configuration.

        The method is not called ``settings`` because that name shadows
        ``APIView.settings`` -- DRF's cached property for the framework
        configuration -- and every request to this view would then fail
        with ``'function' object has no attribute 'FORMAT_SUFFIX_KWARG'``.
        The URL is unaffected: it comes from ``url_path``.
        """
        clinic = self.get_object()
        if request.method == "PATCH":
            if not self._is_admin(clinic):
                return Response(
                    {"error": {"code": "forbidden", "message": "Only a clinic admin can change settings."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            config, _ = ClinicSettings.objects.get_or_create(clinic=clinic)
            serializer = ClinicSettingsSerializer(config, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save(updated_by=request.user)
            record_audit(
                action=AuditAction.UPDATE,
                resource_type="clinic_settings",
                resource_id=clinic.id,
                clinic_id=clinic.id,
                actor=request.user,
                request=request,
            )
            return Response(serializer.data)
        config, _ = ClinicSettings.objects.get_or_create(clinic=clinic)
        return Response(ClinicSettingsSerializer(config).data)

    @action(detail=True, methods=["get", "post"], url_path="members")
    def members(self, request, pk=None):  # noqa: ANN001
        clinic = self.get_object()
        if request.method == "POST":
            if not self._is_admin(clinic):
                return Response(
                    {"error": {"code": "forbidden", "message": "Only a clinic admin can add members."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            serializer = MembershipCreateSerializer(
                data=request.data, context={"clinic": clinic}
            )
            serializer.is_valid(raise_exception=True)
            membership = serializer.save()
            record_audit(
                action=AuditAction.CREATE,
                resource_type="clinic_membership",
                resource_id=membership.id,
                clinic_id=clinic.id,
                actor=request.user,
                request=request,
                metadata={"role": membership.role},
            )
            return Response(
                MembershipSerializer(membership).data, status=status.HTTP_201_CREATED
            )
        memberships = clinic.memberships.select_related("user").all()
        return Response(MembershipSerializer(memberships, many=True).data)

    @action(detail=True, methods=["get"], url_path="provider-connections")
    def provider_connections(self, request, pk=None):  # noqa: ANN001
        clinic = self.get_object()
        if not self._is_admin(clinic):
            return Response(
                {"error": {"code": "forbidden", "message": "Only a clinic admin can view integrations."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        connections = ProviderConnection.objects.filter(clinic=clinic)
        return Response(ProviderConnectionSerializer(connections, many=True).data)

    @action(detail=True, methods=["get"], url_path="configuration")
    def configuration(self, request, pk=None):  # noqa: ANN001
        """Which configuration keys this clinic has, and which are missing.

        Admin only. The response says *whether* each key is set and where
        the value came from. It never contains a secret value -- there is
        no field for one.
        """
        clinic = self.get_object()
        if not self._is_admin(clinic):
            return Response(
                {
                    "error": {
                        "code": "forbidden",
                        "message": "Only a clinic admin can view the configuration.",
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        described = describe_configuration(clinic)
        return Response(
            {
                "clinic_id": str(clinic.id),
                "keys": described,
                "groups": [
                    {
                        "key": group,
                        "label": GROUP_LABELS.get(group, group.title()),
                        "keys": [item["key"] for item in described if item["group"] == group],
                    }
                    for group in GROUP_ORDER
                    if any(item["group"] == group for item in described)
                ],
                "summary": {
                    "total": len(described),
                    "set": sum(1 for item in described if item["status"] == "set"),
                    "platform": sum(1 for item in described if item["status"] == "platform"),
                    "missing": sum(1 for item in described if item["status"] == "missing"),
                    "missing_required": sum(
                        1
                        for item in described
                        if item["status"] == "missing" and item["required"]
                    ),
                },
            }
        )

    @action(detail=True, methods=["put", "delete"], url_path="configuration/(?P<key>[^/]+)")
    def configuration_key(self, request, pk=None, key=None):  # noqa: ANN001
        """Set or remove one configuration key for this clinic.

        Admin only. The value is encrypted before it is stored and is
        never echoed back.
        """
        clinic = self.get_object()
        if not self._is_admin(clinic):
            return Response(
                {
                    "error": {
                        "code": "forbidden",
                        "message": "Only a clinic admin can change the configuration.",
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        spec = get_key_spec(key)
        if spec is None:
            return Response(
                {
                    "error": {
                        "code": "unknown_key",
                        "message": f"'{key}' is not a configuration key.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if spec.scope != SCOPE_CLINIC:
            return Response(
                {
                    "error": {
                        "code": "not_clinic_scoped",
                        "message": (
                            f"'{spec.label}' is a platform setting. It is changed by whoever "
                            "runs the platform, not by a clinic."
                        ),
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == "DELETE":
            removed = clear_clinic_value(clinic, key)
            if removed:
                record_audit(
                    action=AuditAction.DELETE,
                    resource_type="clinic_secret",
                    resource_id=key,
                    clinic_id=clinic.id,
                    actor=request.user,
                    request=request,
                )
            described = describe_configuration(clinic)
            return Response(
                {"removed": removed, "key": next(i for i in described if i["key"] == key)}
            )

        value = (request.data.get("value") or "").strip()
        if not value:
            return Response(
                {
                    "error": {
                        "code": "missing_value",
                        "message": "Enter the value for this key.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        set_clinic_value(clinic, key, value, actor=request.user)
        record_audit(
            action=AuditAction.UPDATE,
            resource_type="clinic_secret",
            resource_id=key,
            clinic_id=clinic.id,
            actor=request.user,
            request=request,
            # The value is never recorded -- only which key was set.
            metadata={"key": key},
        )
        described = describe_configuration(clinic)
        return Response(
            {"key": next(item for item in described if item["key"] == key)},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="channel-numbers")
    def channel_numbers(self, request, pk=None):  # noqa: ANN001
        clinic = self.get_object()
        numbers = ClinicChannelNumber.objects.filter(clinic=clinic)
        return Response(ClinicChannelNumberSerializer(numbers, many=True).data)

    @action(detail=True, methods=["get"], url_path="agent-config")
    def agent_config(self, request, pk=None):  # noqa: ANN001
        clinic = self.get_object()
        config = (
            ClinicAgentConfig.objects.filter(clinic=clinic, is_default=True)
            .order_by("-configuration_version")
            .first()
        )
        if config is None:
            return Response({})
        return Response(ClinicAgentConfigSerializer(config).data)

    def _is_admin(self, clinic) -> bool:  # noqa: ANN001
        """Is the caller an admin *of this clinic* (or a platform admin)?"""
        user = getattr(self.request, "user", None)
        if user is not None and getattr(user, "is_platform_admin", False):
            return True
        if getattr(self.request, "clinic_role", "") != "clinic_admin":
            return False
        # The membership must belong to the clinic being operated on.
        return getattr(self.request, "clinic", None) == clinic or clinic.id == getattr(
            getattr(self.request, "clinic", None), "id", None
        )


class MembershipViewSet(TenantAwareModelViewSet):
    """Update a membership's role or status."""

    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated, IsClinicMember]

    def get_queryset(self):
        clinic = getattr(self.request, "clinic", None)
        if clinic is None:
            return ClinicMembership.objects.none()
        return ClinicMembership.objects.filter(clinic=clinic).select_related("user")

    def get_permissions(self):
        if self.action in {"update", "partial_update", "destroy"}:
            return [IsAuthenticated(), IsClinicAdmin()]
        return [IsAuthenticated(), IsClinicMember()]

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        role = request.data.get("role")
        if role and role != instance.role:
            if instance.user_id == request.user.id and role != "clinic_admin":
                return Response(
                    {
                        "error": {
                            "code": "cannot_demote_last_admin",
                            "message": "You cannot remove your own admin role.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        response = super().partial_update(request, *args, **kwargs)
        record_audit(
            action=AuditAction.UPDATE,
            resource_type="clinic_membership",
            resource_id=instance.id,
            clinic_id=instance.clinic_id,
            actor=request.user,
            request=request,
            metadata={"role": instance.role, "status": instance.status},
        )
        return response
