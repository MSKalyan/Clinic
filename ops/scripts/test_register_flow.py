"""Verify the registration flow the frontend uses.

The frontend's register page does three things in sequence:

1. ``POST /auth/register/``      -- create the person
2. ``POST /auth/login/``         -- get a token (the clinic endpoint needs one)
3. ``POST /clinics/``            -- create the clinic (and the admin membership)

This script exercises exactly that sequence against a running server.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000") + "/api/v1"


def call(method, path, token=None, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    email = f"newcomer-{suffix}@example.test"
    password = "a-long-enough-password"
    clinic_name = f"Test Clinic {suffix}"
    slug = f"test-clinic-{suffix}"

    failures = []

    status, raw = call(
        "POST",
        "/auth/register/",
        body={
            "email": email,
            "password": password,
            "first_name": "Asha",
            "last_name": "Nair",
            "phone": "+919000000999",
        },
    )
    print(f"  {status}  POST /auth/register/")
    if status not in (200, 201):
        failures.append(("register", status, raw[:300]))
        print(raw[:400])
        return 1

    status, raw = call(
        "POST", "/auth/login/", body={"email": email, "password": password}
    )
    print(f"  {status}  POST /auth/login/")
    if status != 200:
        failures.append(("login", status, raw[:300]))
        return 1
    token = json.loads(raw)["tokens"]["access"]

    status, raw = call(
        "POST",
        "/clinics/",
        token=token,
        body={"name": clinic_name, "slug": slug, "timezone": "Asia/Kolkata"},
    )
    print(f"  {status}  POST /clinics/")
    if status not in (200, 201):
        failures.append(("create clinic", status, raw[:300]))
        print(raw[:400])
        return 1

    clinic_id = json.loads(raw)["id"]

    # The creator must be a clinic admin of the clinic they just made.
    status, raw = call("GET", f"/clinics/{clinic_id}/members/", token=token)
    print(f"  {status}  GET /clinics/{{id}}/members/")
    members = json.loads(raw) if status == 200 else []
    admin = next((m for m in members if m.get("role") == "clinic_admin"), None)
    if admin is None:
        failures.append(("membership", status, f"no admin membership in {members}"))

    # And the session must now resolve a clinic.
    status, raw = call("GET", "/auth/me/", token=token)
    print(f"  {status}  GET /auth/me/")
    clinics = json.loads(raw).get("clinics", [])
    if not clinics:
        failures.append(("/auth/me/", status, "no clinic membership returned"))

    if failures:
        print("\nFailures:")
        for label, status, detail in failures:
            print(f"  {label} -> {status}\n    {detail}")
        return 1

    print("\nRegistration flow works: account, clinic, admin membership and session all good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
