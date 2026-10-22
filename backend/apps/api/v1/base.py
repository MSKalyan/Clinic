"""Base API classes that resolve the tenant before permissions are checked.

Django middleware runs before DRF has authenticated the request, so it
cannot see a JWT principal and therefore cannot resolve the tenant on its
own. The tenant is resolved inside the DRF lifecycle instead:

``perform_authentication`` -> resolve the tenant -> ``check_permissions``

That ordering matters: the permission classes need the resolved role, and
the database session has to be scoped to the tenant *before* any tenant
query runs.
"""
from __future__ import annotations

from rest_framework import viewsets
from rest_framework.views import APIView

from apps.core.rls import clear_rls_clinic, set_rls_clinic
from apps.core.tenant import resolve_tenant


class TenantAwareMixin:
    """Resolve the active clinic and scope the database session to it."""

    def perform_authentication(self, request):
        super().perform_authentication(request)
        context = resolve_tenant(request)
        if context.clinic is not None:
            set_rls_clinic(str(context.clinic.id))

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        finally:
            # A pooled connection must never carry another tenant's scope
            # into the next request.
            clear_rls_clinic()


class TenantAwareAPIView(TenantAwareMixin, APIView):
    """An ``APIView`` that resolves the tenant."""


class TenantAwareViewSet(TenantAwareMixin, viewsets.ViewSet):
    """A ``ViewSet`` that resolves the tenant."""


class TenantAwareModelViewSet(TenantAwareMixin, viewsets.ModelViewSet):
    """A ``ModelViewSet`` that resolves the tenant."""
