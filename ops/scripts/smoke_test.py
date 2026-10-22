"""Smoke-test every endpoint the dashboard depends on against a live server.

Usage:
    python ops/scripts/smoke_test.py [base_url]

Exits non-zero if any endpoint answers 5xx.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000") + "/api/v1"


def call(method, path, token=None, clinic_id=None, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if clinic_id:
        request.add_header("X-Clinic-Id", clinic_id)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def main() -> int:
    status, raw = call(
        "POST",
        "/auth/login/",
        body={"email": "admin@sunriseclinic.test", "password": "demo-password-123"},
    )
    if status != 200:
        print(f"login failed: {status} {raw[:200]}")
        return 1
    payload = json.loads(raw)
    token = payload["tokens"]["access"]

    status, raw = call("GET", "/auth/me/", token=token)
    clinic_id = json.loads(raw)["clinics"][0]["clinic_id"]

    status, raw = call("GET", "/doctors/", token=token, clinic_id=clinic_id)
    doctor = json.loads(raw)["results"][0]["id"]

    status, raw = call("GET", "/patients/", token=token, clinic_id=clinic_id)
    patients = json.loads(raw)["results"]
    patient = patients[0]["id"] if patients else "none"

    endpoints = [
        ("GET", "/dashboard/summary/"),
        ("GET", "/doctors/"),
        ("GET", f"/doctors/{doctor}/"),
        ("GET", f"/doctors/{doctor}/availability/"),
        ("GET", f"/doctors/{doctor}/status-history/"),
        ("GET", f"/doctors/{doctor}/schedules/"),
        ("GET", f"/doctors/{doctor}/schedule-exceptions/"),
        ("GET", f"/doctors/{doctor}/availability-events/"),
        ("GET", "/appointments/"),
        ("GET", "/patients/"),
        ("GET", f"/patients/{patient}/"),
        ("GET", f"/patients/{patient}/consents/"),
        ("GET", f"/patients/{patient}/appointments/"),
        ("GET", "/follow-ups/"),
        ("GET", "/conversations/"),
        ("GET", "/call-logs/"),
        ("GET", "/availability/slots/"),
        ("GET", f"/clinics/{clinic_id}/"),
        ("GET", f"/clinics/{clinic_id}/settings/"),
        ("GET", f"/clinics/{clinic_id}/members/"),
        ("GET", f"/clinics/{clinic_id}/channel-numbers/"),
        ("GET", f"/clinics/{clinic_id}/agent-config/"),
        ("GET", f"/clinics/{clinic_id}/provider-connections/"),
        ("GET", "/tools/"),
        ("GET", "/health/"),
        ("GET", "/health/ready/"),
    ]

    failures = []
    for method, path in endpoints:
        status, raw = call(method, path, token=token, clinic_id=clinic_id)
        flag = "FAIL" if status >= 500 else "ok"
        if status >= 500:
            failures.append((path, status, raw[:300]))
        print(f"  {flag:4}  {status}  {path}")

    if failures:
        print("\nFailures:")
        for path, status, raw in failures:
            print(f"  {path} -> {status}\n    {raw}")
        return 1

    print(f"\nAll {len(endpoints)} endpoints answered without a 5xx.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
