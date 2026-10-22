"""Check the CORS contract the way a browser enforces it.

A browser does not "make a request and see if it works". For any request
with a custom header it:

1. sends a **preflight** (``OPTIONS``) and reads
   ``Access-Control-Allow-Headers``;
2. only sends the real request if the preflight named every header the
   real request carries;
3. rejects the response if ``Access-Control-Allow-Origin`` does not match.

This script performs exactly those steps, so a preflight that answers
200 but forgets to name ``X-Clinic-Id`` is caught here -- which is the
bug that made every dashboard screen show "Failed to fetch".

Usage:
    python ops/scripts/check_cors.py [base_url] [origin]
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
ORIGIN = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:3000"

#: The headers the dashboard sends on a tenant-scoped request.
DASHBOARD_HEADERS = "authorization, x-clinic-id"

CHECKS = [
    ("/api/v1/dashboard/summary/", "GET", DASHBOARD_HEADERS),
    ("/api/v1/appointments/", "GET", DASHBOARD_HEADERS),
    ("/api/v1/follow-ups/", "GET", DASHBOARD_HEADERS),
    ("/api/v1/patients/", "POST", DASHBOARD_HEADERS),
    ("/api/v1/clinics/", "POST", "authorization"),
]


def _headers(raw) -> dict[str, str]:
    """Header names arrive lower-cased over the wire.

    A plain dict lookup would then miss ``Access-Control-Allow-Origin``
    and report a false failure, so the keys are normalised here.
    """
    return {key.lower(): value for key, value in raw.items()}


def request(method, path, headers=None):
    req = urllib.request.Request(f"{BASE}{path}", method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, _headers(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, _headers(error.headers), error.read().decode()


def check(path, method, requested_headers):
    print(f"\n  {method} {path}")
    failures = []

    # 1. The preflight.
    status, headers, _ = request(
        "OPTIONS",
        path,
        {
            "Origin": ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": requested_headers,
        },
    )
    print(f"    preflight -> {status}")

    if status >= 400:
        failures.append(f"preflight answered {status}")
        return failures

    allowed_headers = {
        item.strip().lower()
        for item in headers.get("access-control-allow-headers", "").split(",")
        if item.strip()
    }
    allowed_methods = {
        item.strip()
        for item in headers.get("access-control-allow-methods", "").split(",")
        if item.strip()
    }
    allow_origin = headers.get("access-control-allow-origin", "")

    # 2. Every header the real request carries must be allowed.
    for header in (h.strip().lower() for h in requested_headers.split(",")):
        if header not in allowed_headers:
            failures.append(
                f"the preflight does not allow '{header}' "
                f"(it allows: {', '.join(sorted(allowed_headers)) or 'nothing'})"
            )
        else:
            print(f"    allows header: {header}")

    if method not in allowed_methods:
        failures.append(f"the preflight does not allow the method '{method}'")
    else:
        print(f"    allows method: {method}")

    # 3. The origin has to match exactly.
    if allow_origin != ORIGIN:
        failures.append(
            f"Access-Control-Allow-Origin is '{allow_origin}', expected '{ORIGIN}'"
        )
    else:
        print(f"    allows origin: {allow_origin}")

    return failures


def main() -> int:
    print(f"Checking CORS for {BASE} from {ORIGIN}")

    failures = []
    for path, method, headers in CHECKS:
        failures.extend(
            f"{method} {path}: {reason}" for reason in check(path, method, headers)
        )

    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nA browser would refuse these requests and the dashboard would show "
            "'Failed to fetch'."
        )
        return 1

    print(f"\nAll {len(CHECKS)} request shapes pass the CORS preflight.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
