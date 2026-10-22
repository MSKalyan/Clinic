"""Audit trail helper.

Audit rows deliberately avoid patient content. Only identifiers, action names
and small structured metadata are stored (PRD 9.6 / 12.2).
"""
from __future__ import annotations

import logging
from typing import Any

from apps.core.constants import AuditAction
from apps.core.middleware import request_id_var
from apps.core.models import AuditLog

logger = logging.getLogger("apps.core.audit")

#: Metadata keys that must never be written to the audit log.
_FORBIDDEN_METADATA_KEYS = {
    "phone",
    "phone_number",
    "message",
    "body",
    "content",
    "transcript",
    "recording_url",
    "dob",
    "date_of_birth",
    "address",
    "email",
}


def sanitise_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if key.lower() not in _FORBIDDEN_METADATA_KEYS
    }


def record_audit(
    *,
    action: AuditAction | str,
    resource_type: str,
    resource_id: str | uuid.UUID | int | None = None,
    clinic_id: uuid.UUID | None = None,
    actor=None,
    request=None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog | None:
    """Write an audit entry. Never raises into the caller's happy path.

    A failed audit write must not roll back the work the user actually
    asked for -- losing a booking because the audit table was momentarily
    unhappy would be worse than a missing trail entry. The failure is
    logged loudly instead, so it can be found afterwards.

    Returns the created row, or ``None`` when the write failed.
    """
    actor_id = None
    actor_role = ""
    if actor is not None:
        actor_id = getattr(actor, "id", None)
        actor_role = getattr(actor, "role", "") or ""

    request_id = ""
    if request is not None:
        request_id = getattr(request, "request_id", "") or ""
    if not request_id:
        request_id = request_id_var.get()

    if ip_address is None and request is not None:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        ip_address = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")

    try:
        return AuditLog.objects.create(
            clinic_id=clinic_id,
            actor_id=actor_id,
            actor_role=str(actor_role),
            action=str(action),
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else "",
            request_id=request_id,
            ip_address=ip_address,
            metadata=sanitise_metadata(metadata),
        )
    except Exception:  # pragma: no cover - auditing must not break the request
        logger.exception("failed to write audit log entry")
        return None
