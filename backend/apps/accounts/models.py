"""Users, clinic memberships and provider service tokens."""
from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.constants import MembershipStatus, Role
from apps.core.models import UUIDModel


class User(AbstractUser):
    """Platform user. Access to clinic data is granted by membership."""

    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, blank=True, default="")
    is_platform_admin = models.BooleanField(default=False)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return self.email or self.username

    def memberships(self):
        return self.clinic_memberships.filter(status=MembershipStatus.ACTIVE)

    def role_for(self, clinic) -> str | None:  # noqa: ANN001
        membership = self.clinic_memberships.filter(clinic=clinic).first()
        return membership.role if membership else None


class ClinicMembership(UUIDModel):
    """Links a user to a clinic with exactly one role."""

    clinic = models.ForeignKey(
        "tenancy.Clinic", on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="clinic_memberships")
    role = models.CharField(max_length=30, choices=[(r.value, r.value) for r in Role])
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in MembershipStatus],
        default=MembershipStatus.INVITED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clinic_memberships"
        constraints = [
            models.UniqueConstraint(fields=["clinic", "user"], name="uniq_clinic_membership")
        ]
        indexes = [models.Index(fields=["user", "status"], name="membership_user_status_idx")]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.user_id}@{self.clinic_id} as {self.role}"

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE


class ClinicServiceToken(UUIDModel):
    """A clinic-scoped credential used by the voice/messaging providers.

    The token *is* the tenant binding: the provider never chooses the
    clinic, it presents a token that already maps to exactly one clinic.
    Only a hash of the token is stored.
    """

    clinic = models.ForeignKey(
        "tenancy.Clinic", on_delete=models.CASCADE, related_name="service_tokens"
    )
    name = models.CharField(max_length=120, default="default")
    token_hash = models.CharField(max_length=128, unique=True)
    scopes = models.JSONField(default=list, blank=True)
    provider_type = models.CharField(max_length=30, default="")
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_service_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "clinic_service_tokens"
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"ServiceToken({self.name} for {self.clinic_id})"

    @property
    def is_active(self) -> bool:
        from django.utils import timezone

        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return True
