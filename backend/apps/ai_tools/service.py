"""Tool invocation service.

This is the single entry point the voice agent and the WhatsApp assistant
use. It applies the permission rules, resolves the tenant, and returns a
result the assistant can speak.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.ai_tools.registry import Tool, get_tool
from apps.core.exceptions import DomainError, TenantAccessDenied
from apps.core.middleware import request_id_var

logger = logging.getLogger("apps.ai_tools.service")


class ToolInvocationError(DomainError):
    status_code = 403
    default_code = "tool_forbidden"
    default_detail = "You are not allowed to call this tool."


def invoke(
    *,
    clinic,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    actor=None,
    role: str = "",
    interaction_id: str = "",
    caller_phone: str = "",
    idempotency_key: str = "",
    booking_source: str = "",
    request=None,
) -> dict[str, Any]:
    """Validate and run a tool call."""
    tool: Tool | None = get_tool(tool_name)
    if tool is None:
        raise DomainError(
            f"Unknown tool '{tool_name}'.", code="unknown_tool", status_code=404
        )

    arguments = arguments or {}

    # -- permission ---------------------------------------------------
    is_service_token = role == "service_token"
    is_platform_admin = role == "platform_admin"
    if tool.staff_only and is_service_token:
        raise ToolInvocationError(
            f"'{tool.name}' can only be called by an authenticated member of staff.",
            details={"tool": tool.name},
        )
    if not is_service_token and not is_platform_admin and role and role not in tool.allowed_roles:
        raise ToolInvocationError(
            f"Your role ({role}) is not allowed to call '{tool.name}'.",
            details={"tool": tool.name, "role": role},
        )
    if not is_service_token and not is_platform_admin and not role:
        raise ToolInvocationError("A staff role is required to call this tool.")

    # -- validation ---------------------------------------------------
    _validate_arguments(tool, arguments)

    context: dict[str, Any] = {
        "actor": actor,
        "role": role,
        "interaction_id": interaction_id,
        "caller_phone": caller_phone,
        "idempotency_key": idempotency_key or (f"{clinic.id}:{interaction_id}:{tool.name}" if interaction_id else ""),
        "booking_source": booking_source,
        "request_id": request_id_var.get(),
    }

    logger.info(
        "tool invoked clinic=%s tool=%s role=%s", clinic.id, tool.name, role or "service_token"
    )
    result = tool.handler(clinic, arguments, context)
    if not isinstance(result, dict):
        result = {"result": result}
    result.setdefault("tool", tool.name)
    return result


def _validate_arguments(tool: Tool, arguments: dict[str, Any]) -> None:
    schema = tool.input_schema or {}
    required = schema.get("required", [])
    missing = [field for field in required if arguments.get(field) in (None, "")]
    if missing:
        raise DomainError(
            f"Missing required argument(s): {', '.join(missing)}.",
            code="missing_arguments",
            details={"missing": missing, "tool": tool.name},
        )

    properties = schema.get("properties", {})
    unknown = [key for key in arguments if key not in properties]
    if unknown:
        raise DomainError(
            f"Unknown argument(s): {', '.join(unknown)}.",
            code="unknown_arguments",
            details={"unknown": unknown, "tool": tool.name},
        )
