"""Request middleware: correlation IDs and tenant-scope hygiene."""
from __future__ import annotations

import contextvars
import logging
import uuid

from django.http import HttpRequest, HttpResponse

from apps.core.rls import clear_rls_clinic

logger = logging.getLogger("apps.core.middleware")

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)
current_clinic_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_clinic_id", default=""
)


class RequestIDMiddleware:
    """Attach a correlation id to every request and response."""

    def __init__(self, get_response):  # noqa: ANN001
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.request_id = request_id  # type: ignore[attr-defined]
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response["X-Request-Id"] = request_id
        return response


class TenantContextMiddleware:
    """Guarantee that a connection never carries a stale tenant scope.

    The tenant itself is resolved inside the DRF lifecycle (see
    ``apps.core.tenant``) because Django middleware runs before DRF has
    authenticated the caller -- at that point the JWT principal, and
    therefore the tenant, is not known yet.

    What the middleware *can* do is make sure that a pooled PostgreSQL
    connection is never reused with another tenant's Row Level Security
    scope still applied. The scope itself is set by the API layer once the
    tenant has been verified.
    """

    def __init__(self, get_response):  # noqa: ANN001
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        clear_rls_clinic()
        try:
            response = self.get_response(request)
        finally:
            clear_rls_clinic()
        return response
