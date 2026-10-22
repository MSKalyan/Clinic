"""Service health endpoints.

These are used by the container orchestrator, the load balancer and the
reverse proxy to decide whether this instance can take traffic. They must
stay cheap: no database writes, no tenant context, no audit log.
"""
from __future__ import annotations

from django.db import connection
from django.http import JsonResponse
from django.views import View


class LivenessView(View):
    """Is the process alive?

    Deliberately does not touch the database. A liveness probe that fails
    because Postgres is slow causes a restart loop that fixes nothing.
    """

    def get(self, request):  # noqa: ANN001
        return JsonResponse({"status": "ok"})


class ReadinessView(View):
    """Can this instance serve requests?

    Checks that the database is reachable. A readiness failure removes the
    instance from the load balancer without killing it.
    """

    def get(self, request):  # noqa: ANN001
        checks = {"database": "ok"}
        status_code = 200

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:  # noqa: BLE001 - any failure means "not ready"
            checks["database"] = "unavailable"
            status_code = 503

        return JsonResponse(
            {
                "status": "ok" if status_code == 200 else "degraded",
                "checks": checks,
            },
            status=status_code,
        )
