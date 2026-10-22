"""The dashboard talks to the API from a browser, so CORS is not optional.

The bug this file exists to prevent: the tenant is selected with the
``X-Clinic-Id`` header. A custom header turns every request into a
preflight. django-cors-headers' default allow-list contains no custom
headers, so the preflight answered 200 *without* naming ``X-Clinic-Id``,
and the browser then refused the real request.

The symptom was "Failed to fetch" on every screen of the dashboard, while
the server log showed a perfectly healthy 200 for the preflight and
nothing at all for the request that followed. It looked like the backend
was broken; it was the preflight.

These tests drive a real preflight and check the response, because that
is what the browser reads.
"""
from __future__ import annotations

import pytest
from django.test import Client

ORIGIN = "http://localhost:3000"


@pytest.fixture
def preflight():
    """Issue a CORS preflight for a dashboard request."""

    def _preflight(path="/api/v1/dashboard/summary/", headers="authorization, x-clinic-id"):
        client = Client()
        return client.options(
            path,
            HTTP_ORIGIN=ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS=headers,
        )

    return _preflight


def _allowed_headers(response) -> set[str]:
    raw = response.headers.get("Access-Control-Allow-Headers", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def test_the_preflight_allows_the_tenant_header(preflight):
    """``X-Clinic-Id`` must be named in the preflight response."""
    response = preflight()

    assert response.status_code == 200
    assert "x-clinic-id" in _allowed_headers(response), (
        "the preflight does not allow X-Clinic-Id, so the browser refuses "
        "the real request and every screen shows 'Failed to fetch'"
    )


def test_the_preflight_allows_authorization(preflight):
    """The bearer token is a custom header too."""
    response = preflight(headers="authorization")

    assert "authorization" in _allowed_headers(response)


def test_the_preflight_allows_the_methods_the_dashboard_uses(preflight):
    """Booking, cancelling and editing all need their verbs allowed."""
    client = Client()
    for method in ("POST", "PATCH", "DELETE", "PUT"):
        response = client.options(
            "/api/v1/appointments/",
            HTTP_ORIGIN=ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD=method,
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization, x-clinic-id",
        )
        allowed = {
            item.strip()
            for item in response.headers.get("Access-Control-Allow-Methods", "").split(",")
        }
        assert method in allowed, f"{method} is not in the CORS allow-list"


def test_the_preflight_names_the_requesting_origin(preflight):
    """The origin has to be echoed back, or the browser blocks it."""
    response = preflight()

    assert response.headers.get("Access-Control-Allow-Origin") == ORIGIN


def test_the_configured_header_list_contains_the_tenant_header():
    """Guard the setting itself, so a refactor cannot drop it silently."""
    from django.conf import settings

    allowed = {header.lower() for header in settings.CORS_ALLOW_HEADERS}
    assert "x-clinic-id" in allowed


def test_health_is_reachable_at_the_root(db):
    """Health checks use the conventional path, without the API prefix."""
    client = Client()

    for path in ("/health", "/health/", "/api/v1/health/"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} answered {response.status_code}"


def test_readiness_is_reachable_at_the_root(db):
    # The readiness check touches the database, so the test needs one.
    client = Client()

    for path in ("/health/ready", "/health/ready/", "/api/v1/health/ready/"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} answered {response.status_code}"
