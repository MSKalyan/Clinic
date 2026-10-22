"""Tenant resolution.

The active clinic is derived **only** from trusted sources:

1. a clinic-scoped **service token** -- the clinic is baked into the token,
   so a provider can never choose a tenant;
2. the caller's **clinic membership** -- proved by the JWT/session identity
   and the ``X-Clinic-Id`` header.

It is never taken from a request body, a query parameter, a webhook payload
or anything the language model produced. Provider webhooks resolve their
tenant from *routing metadata* instead (the number that was dialled or that
received the message) -- see ``apps.integrations.services.webhooks``.

Because Django middleware runs before DRF has authenticated the request, the
resolution happens inside the DRF lifecycle: after authentication (so we
know who the caller is) and before the permission classes run (so they can
see the resolved role).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from apps.core.constants import MembershipStatus

logger = logging.getLogger("apps.core.tenant")


@dataclass(frozen=True)
class TenantContext:
    """The resolved tenant for one request."""

    clinic: Any = None
    role: str = ""
    membership: Any = None
    source: str = "none"

    @property
    def is_scoped(self) -> bool:
        return self.clinic is not None

    @property
    def clinic_id(self) -> Any:
        return getattr(self.clinic, "id", None)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def resolve_tenant(request) -> TenantContext:
    """Resolve the active clinic for a request and attach it to ``request``.

    Sets ``request.clinic``, ``request.clinic_role`` and ``request.membership``
    so that the permission classes and the tenant-scoped querysets can use
    them.
    """
    context = _resolve(request)
    request.tenant = context
    request.clinic = context.clinic
    request.clinic_role = context.role
    request.membership = context.membership
    return context


def _resolve(request) -> TenantContext:
    # --- 1. Service token: the tenant *is* the token ------------------------
    # ``request.user`` is the *principal* returned by the authenticator, so a
    # service-token call arrives as a ``ServiceTokenPrincipal``. ``request.auth``
    # is the credential itself (the token row), which carries no role.
    principal = getattr(request, "user", None)
    if principal is not None and getattr(principal, "role", "") == "service_token":
        clinic = getattr(principal, "clinic", None)
        if clinic is not None:
            return TenantContext(clinic=clinic, role="service_token", source="service_token")
        return TenantContext(source="service_token_without_clinic")

    # --- 2. Staff member: the header selects a clinic they belong to ------
    user = principal
    if user is None or not getattr(user, "is_authenticated", False):
        return TenantContext(source="anonymous")

    clinic_id = (request.headers.get(settings.CLINIC_HEADER) or "").strip()
    if not clinic_id:
        return TenantContext(source="no_clinic_header")
    if not _is_uuid(clinic_id):
        logger.info("rejected a non-UUID %s header", settings.CLINIC_HEADER)
        return TenantContext(source="invalid_clinic_id")

    from apps.accounts.models import ClinicMembership

    membership = (
        ClinicMembership.objects.select_related("clinic")
        .filter(
            clinic_id=clinic_id,
            user=user,
            status=MembershipStatus.ACTIVE,
        )
        .first()
    )
    if membership is not None:
        return TenantContext(
            clinic=membership.clinic,
            role=membership.role,
            membership=membership,
            source="membership",
        )

    # --- 3. Platform administrators may operate any clinic -----------------
    if getattr(user, "is_platform_admin", False):
        from apps.tenancy.models import Clinic

        clinic = Clinic.objects.filter(id=clinic_id).first()
        if clinic is not None:
            return TenantContext(clinic=clinic, role="platform_admin", source="platform_admin")

    return TenantContext(source="no_membership")
