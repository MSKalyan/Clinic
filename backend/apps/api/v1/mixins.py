"""Shared view mixins that enforce tenant scoping."""
from __future__ import annotations

from apps.api.v1.base import TenantAwareModelViewSet
from apps.core.exceptions import TenantAccessDenied


class TenantScopedViewSet(TenantAwareModelViewSet):
    """Base viewset that scopes every query and write to the active clinic.

    The clinic comes from the request context, which the tenant resolver
    derives from a trusted source (a staff membership or a clinic-scoped
    service token). It can never be taken from the request body.
    """

    #: Model attribute used to detect the model of this viewset.
    model = None

    def get_clinic(self):
        clinic = getattr(self.request, "clinic", None)
        if clinic is None:
            raise TenantAccessDenied("No clinic context for this request.")
        return clinic

    def get_queryset(self):
        clinic = getattr(self.request, "clinic", None)
        if clinic is None:
            return self.model.objects.none()
        return self.model.objects.filter(clinic=clinic)

    def perform_create(self, serializer) -> None:
        serializer.save(clinic=self.get_clinic())

    def perform_update(self, serializer) -> None:
        serializer.save(clinic=self.get_clinic())

    def check_object_permissions(self, request, obj) -> None:
        super().check_object_permissions(request, obj)
        clinic = getattr(request, "clinic", None)
        if clinic is not None and getattr(obj, "clinic_id", None) != clinic.id:
            # Never disclose the existence of another tenant's object.
            raise TenantAccessDenied("That resource does not belong to this clinic.")
