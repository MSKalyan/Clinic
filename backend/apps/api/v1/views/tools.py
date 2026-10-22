"""AI tool endpoints.

Sarvam's "API tool" feature calls one HTTP endpoint per tool, so the URL
carries the tool name. Each endpoint validates the tenant, the caller's
permissions and the arguments before running anything.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.ai_tools.registry import all_tools, get_tool, tool_specs
from apps.api.v1.base import TenantAwareAPIView
from apps.ai_tools.service import invoke
from apps.core.audit import record_audit
from apps.core.constants import AuditAction
from apps.core.exceptions import DomainError, TenantAccessDenied


class ToolListView(TenantAwareAPIView):
    """The tools available to the assistant, with their schemas."""

    permission_classes = [IsAuthenticated]

    def get(self, request):  # noqa: ANN001
        clinic = getattr(request, "clinic", None)
        if clinic is None:
            # No tenant was resolved, so there is no tool catalogue to
            # describe. A caller without a clinic membership gets nothing.
            raise TenantAccessDenied("No clinic context for this request.")

        role = getattr(request, "clinic_role", "")
        specs = []
        for tool in all_tools():
            if tool.staff_only and role == "service_token":
                continue
            if (
                role
                and role != "service_token"
                and role != "platform_admin"
                and role not in tool.allowed_roles
            ):
                continue
            specs.append(tool.spec())
        return Response({"clinic_id": str(clinic.id), "tools": specs})


class ToolInvokeView(TenantAwareAPIView):
    """Invoke one tool."""

    permission_classes = [IsAuthenticated]

    def post(self, request, tool_name: str):  # noqa: ANN001
        clinic = getattr(request, "clinic", None)
        if clinic is None:
            raise TenantAccessDenied("No clinic context for this request.")

        tool = get_tool(tool_name)
        if tool is None:
            raise DomainError(
                f"Unknown tool '{tool_name}'.", code="unknown_tool", status_code=404
            )

        payload = request.data or {}
        arguments = payload.get("arguments")
        if arguments is None:
            # Allow a flat body as well as {"arguments": {...}}.
            arguments = {
                key: value
                for key, value in payload.items()
                if key not in {"arguments", "interaction_id", "caller_phone", "context"}
            }
        if not isinstance(arguments, dict):
            raise DomainError("'arguments' must be an object.", code="invalid_arguments")

        context_payload = payload.get("context") or {}
        interaction_id = str(
            payload.get("interaction_id") or context_payload.get("interaction_id") or ""
        )
        caller_phone = str(
            payload.get("caller_phone") or context_payload.get("caller_phone") or ""
        )

        user = getattr(request, "user", None)
        # The *principal* is the service token, and it is exposed as
        # ``request.user``; ``request.auth`` is the credential itself.
        is_service_token = getattr(user, "role", "") == "service_token"
        role = getattr(request, "clinic_role", "") or ("service_token" if is_service_token else "")

        result = invoke(
            clinic=clinic,
            tool_name=tool_name,
            arguments=arguments,
            actor=user if not is_service_token else None,
            role=role,
            interaction_id=interaction_id,
            caller_phone=caller_phone,
            idempotency_key=context_payload.get("idempotency_key", ""),
            booking_source=context_payload.get("booking_source", ""),
            request=request,
        )

        if tool_name in {"book_appointment", "reschedule_appointment", "cancel_appointment"}:
            record_audit(
                action=AuditAction.BOOK
                if tool_name == "book_appointment"
                else AuditAction.RESCHEDULE
                if tool_name == "reschedule_appointment"
                else AuditAction.CANCEL,
                resource_type="appointment",
                resource_id=result.get("appointment", {}).get("appointment_id", ""),
                clinic_id=clinic.id,
                actor=user if not is_service_token else None,
                request=request,
                metadata={"tool": tool_name, "source": role},
            )

        return Response(result, status=status.HTTP_200_OK)
