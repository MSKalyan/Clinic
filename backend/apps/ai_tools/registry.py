"""Registry of the narrowly scoped operations the AI assistant may invoke.

The assistant never touches the database. It calls one of these tools; each
tool validates its inputs, the tenant context, the caller's permissions and
the business rules before it changes anything (PRD 7.2 / 10.7).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from apps.core.constants import Role

#: Roles that may call a tool as a member of staff.
STAFF_ROLES = {Role.CLINIC_ADMIN.value, Role.DOCTOR.value, Role.RECEPTIONIST.value}


@dataclass(frozen=True)
class Tool:
    """One callable business operation."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]
    #: When set, only these staff roles may call the tool.
    allowed_roles: frozenset[str] = frozenset(STAFF_ROLES)
    #: When True, a provider service token may NOT call this tool.
    #: Used for tools that change clinic state on a human's instruction.
    staff_only: bool = False
    #: When True, replaying the same idempotency key returns the first result.
    idempotent: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "staff_only": self.staff_only,
            "idempotent": self.idempotent,
            "tags": list(self.tags),
        }


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _REGISTRY[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tools() -> list[Tool]:
    return sorted(_REGISTRY.values(), key=lambda t: t.name)


def tool_specs() -> list[dict[str, Any]]:
    return [tool.spec() for tool in all_tools()]
