"""Role-based access control.

Roles live on the *membership*, not the user: the same person can be a
receptionist at one clinic and a clinic admin at another.
"""
from __future__ import annotations

from rest_framework import permissions

from apps.core.constants import Role


def request_role(request) -> str:
    """The role the caller holds in the active clinic."""
    role = getattr(request, "clinic_role", "")
    if role:
        return role
    principal = getattr(request, "auth", None)
    if principal is not None and getattr(principal, "role", "") == "service_token":
        return "service_token"
    return ""


def is_platform_admin(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user and getattr(user, "is_platform_admin", False))


class IsClinicMember(permissions.BasePermission):
    """The caller must have an active membership in the selected clinic."""

    message = "Select a clinic you are a member of, using the X-Clinic-Id header."

    def has_permission(self, request, view) -> bool:  # noqa: ANN001
        clinic = getattr(request, "clinic", None)
        if clinic is None:
            return False
        user = getattr(request, "user", None)
        if user and getattr(user, "is_platform_admin", False):
            return True
        return bool(getattr(request, "clinic_role", ""))


class HasRole(permissions.BasePermission):
    """The caller must hold one of ``allowed_roles`` in the active clinic.

    The failure message says *which* thing was wrong. "You do not have
    permission to perform this action" is true, but it does not tell a
    receptionist whether the dashboard forgot to send the clinic, whether
    they picked a clinic they do not belong to, or whether the operation is
    simply above their role.
    """

    def __init__(self, *allowed_roles: str) -> None:
        self.allowed_roles = {r.value if hasattr(r, "value") else str(r) for r in allowed_roles}
        super().__init__()

    def _message(self, request) -> str:  # noqa: ANN001
        source = getattr(getattr(request, "tenant", None), "source", "none")
        if source == "no_clinic_header":
            return "Select a clinic first. The request carried no clinic."
        if source == "invalid_clinic_id":
            return "That clinic reference is not valid."
        if source == "no_membership":
            return "You are not a member of that clinic."
        if source == "anonymous":
            return "Sign in to continue."
        wanted = ", ".join(sorted(self.allowed_roles))
        return f"This action needs one of these roles in the active clinic: {wanted}."

    def has_permission(self, request, view) -> bool:  # noqa: ANN001
        if not getattr(request, "clinic", None):
            self.message = self._message(request)
            return False
        if is_platform_admin(request):
            return True
        role = request_role(request)
        if not role:
            self.message = self._message(request)
            return False
        if role not in self.allowed_roles:
            self.message = self._message(request)
            return False
        return True


class IsClinicAdmin(HasRole):
    def __init__(self) -> None:
        super().__init__(Role.CLINIC_ADMIN)


class IsStaffMember(HasRole):
    """Any of the three clinic roles."""

    def __init__(self) -> None:
        super().__init__(Role.CLINIC_ADMIN, Role.DOCTOR, Role.RECEPTIONIST)


class IsDoctorOrAdmin(HasRole):
    def __init__(self) -> None:
        super().__init__(Role.CLINIC_ADMIN, Role.DOCTOR)


class IsReceptionistOrAdmin(HasRole):
    def __init__(self) -> None:
        super().__init__(Role.CLINIC_ADMIN, Role.RECEPTIONIST)


class IsPlatformAdmin(permissions.BasePermission):
    message = "This operation is restricted to platform administrators."

    def has_permission(self, request, view) -> bool:  # noqa: ANN001
        return is_platform_admin(request)


class IsNotServiceToken(permissions.BasePermission):
    """Blocks provider service tokens from staff-only operations."""

    message = "This operation requires an authenticated staff member."

    def has_permission(self, request, view) -> bool:  # noqa: ANN001
        return request_role(request) != "service_token"
