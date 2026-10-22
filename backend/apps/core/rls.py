"""PostgreSQL Row Level Security helpers.

Row Level Security (RLS) is the database-level half of tenant isolation.
Every tenant-scoped table carries a ``clinic_id`` column and a policy that
compares it against the ``app.current_clinic_id`` session variable:

.. code-block:: sql

    USING      (clinic_id::text = current_setting('app.current_clinic_id', true))
    WITH CHECK (clinic_id::text = current_setting('app.current_clinic_id', true))

The variable is only ever set from a *verified* tenant context:

* an authenticated staff member's clinic membership;
* a clinic-scoped service token (the clinic is baked into the token);
* trusted routing metadata on a provider webhook (the number dialled).

If no tenant has been established the variable is empty, the policies match
nothing, and the request fails closed: no tenant row is readable and no
tenant row is writable.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any, Iterator

from django.db import connection

logger = logging.getLogger("apps.core.rls")

#: PostgreSQL session variable read by the Row Level Security policies.
RLS_SESSION_VAR = "app.current_clinic_id"


def set_rls_clinic(clinic_id: str | None) -> None:
    """Point the database session at a single clinic.

    An empty value means "no tenant context", which is the safe default:
    the policies then match no row at all.
    """
    value = str(clinic_id) if clinic_id else ""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, false)", [RLS_SESSION_VAR, value])


def clear_rls_clinic() -> None:
    """Remove any tenant scope from the database session."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config(%s, %s, false)", [RLS_SESSION_VAR, ""])
    except Exception:  # pragma: no cover - connection may already be gone
        logger.debug("could not clear the RLS clinic scope", exc_info=True)


def get_rls_clinic() -> str:
    """The clinic the session is currently scoped to ("" when unscoped)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting(%s, true)", [RLS_SESSION_VAR])
            row = cursor.fetchone()
    except Exception:  # pragma: no cover - connection may already be gone
        return ""
    return (row[0] or "") if row else ""


@contextlib.contextmanager
def rls_scope(clinic_id: str | None) -> Iterator[str]:
    """Scope the database session to one clinic for the duration of a block.

    The previous scope is restored on exit, so nested scopes (for example a
    webhook handler that resolves its tenant mid-request) behave.
    """
    previous = get_rls_clinic()
    set_rls_clinic(clinic_id)
    try:
        yield str(clinic_id) if clinic_id else ""
    finally:
        set_rls_clinic(previous)


def iter_clinic_scopes(include_offboarded: bool = False) -> Iterator[tuple[Any, str]]:
    """Yield ``(clinic, scope)`` for every clinic, one tenant at a time.

    Background workers sweep across tenants. Instead of running with a
    database role that bypasses RLS, they iterate the clinics and re-scope
    the session for each one, so a cross-tenant sweep is explicit and the
    queries stay scoped as well.
    """
    from apps.tenancy.models import Clinic

    queryset = Clinic.objects.all()
    if not include_offboarded:
        queryset = queryset.exclude(status="offboarded")
    for clinic in queryset.order_by("created_at").iterator():
        with rls_scope(str(clinic.id)) as scope:
            yield clinic, scope
