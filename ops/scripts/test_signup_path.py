"""Walk the signup path the way the dashboard does.

The frontend's register page does, in order:

1. ``POST /auth/register/``      -- create the person, get tokens
2. ``GET  /auth/me/``            -- resolve the memberships, **with the
                                    token from step 1**
3. ``POST /clinics/``            -- create the clinic
4. ``GET  /auth/me/``            -- re-resolve, now with the membership
5. ``GET  /dashboard/summary/``  -- the first thing the dashboard asks for

Step 2 is the one that used to fail: the request went out without the
new token, the server answered with an empty clinic list, and the user
was told they belonged to no clinic.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000") + "/api/v1"


def call(method, path, token=None, body=None, clinic_id=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
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
    suffix = uuid.uuid4().hex[:8]
    email = f"signup-{suffix}@example.test"
    password = "a-long-enough-password"
    clinic_name = "Test Clinic"
    slug = f"test-clinic-{suffix}"

    failures = []

    # 1. Register.
    status, raw = call(
        "POST",
        "/auth/register/",
        body={"email": email, "password": password, "first_name": "Asha"},
    )
    print(f"  {status}  POST /auth/register/")
    if status not in (200, 201):
        failures.append(("register", status, raw[:300]))
        return 1
    tokens = json.loads(raw)["tokens"]

    # 2. Resolve the memberships -- with the token from step 1.
    status, raw = call("GET", "/auth/me/", token=tokens["access"])
    print(f"  {status}  GET  /auth/me/")
    clinics = json.loads(raw).get("clinics", [])
    print(f"        -> {len(clinics)} clinic(s) before creating one")
    if clinics:
        failures.append(("/auth/me/", status, "a brand new account already has a clinic"))

    # 3. Create the clinic.
    status, raw = call(
        "POST",
        "/clinics/",
        token=tokens["access"],
        body={"name": clinic_name, "slug": slug, "timezone": "Asia/Kolkata"},
    )
    print(f"  {status}  POST /clinics/")
    if status not in (200, 201):
        failures.append(("create clinic", status, raw[:300]))
        return 1
    clinic_id = json.loads(raw)["id"]

    # 4. Re-resolve the memberships.
    status, raw = call("GET", "/auth/me/", token=tokens["access"])
    clinics = json.loads(raw).get("clinics", [])
    print(f"  {status}  GET  /auth/me/  -> {len(clinics)} clinic(s)")
    if not clinics:
        failures.append(("/auth/me/", status, "the new membership did not come back"))
    else:
        print(f"        -> {clinics[0]['name']}  [{clinics[0]['role']}]")

    # 5. The first call the dashboard makes.
    status, raw = call(
        "GET",
        "/dashboard/summary/",
        token=tokens["access"],
        clinic_id=clinic_id,
    )
    print(f"  {status}  GET  /dashboard/summary/")
    if status != 200:
        failures.append(("dashboard", status, raw[:300]))
    else:
        summary = json.loads(raw)
        print(f"        -> {summary['clinic']['name']}, {summary['doctors']['total']} doctors")

    if failures:
        print("\nFailures:")
        for label, status, detail in failures:
            print(f"  {label} -> {status}\n    {detail}")
        return 1

    print("\nThe signup path works end to end: the clinic is resolved and the dashboard loads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
