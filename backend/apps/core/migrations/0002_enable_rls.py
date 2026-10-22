"""Enable PostgreSQL Row Level Security on the tenant-scoped tables.

Row Level Security (RLS) is the database-level half of tenant isolation.
The application already scopes every query to the active clinic; RLS makes
sure that a *missing* filter is a bug that fails closed rather than a data
leak.

The policy compares the row's ``clinic_id`` with the
``app.current_clinic_id`` session variable::

    USING      (clinic_id::text = current_setting('app.current_clinic_id', true))
    WITH CHECK (clinic_id::text = current_setting('app.current_clinic_id', true))

The session variable is only ever set from a verified tenant context (a
staff membership, a clinic-scoped service token, or trusted webhook routing
metadata). When no tenant has been established the variable is empty, the
comparison is never true, and the table is effectively invisible.

``FORCE ROW LEVEL SECURITY`` matters: the application role owns the tables,
and a table owner would otherwise bypass its own policies.

Bootstrap tables
----------------
These tables are deliberately **not** protected by RLS, because they have to
be readable *before* a tenant exists:

``clinics``
    the tenant registry itself.
``users``, ``clinic_memberships``
    the identity that proves which tenant the caller may act for.
``clinic_service_tokens``
    the credential whose *content* is the tenant binding.
``clinic_settings``
    per-clinic configuration, always reached through the resolved clinic.
``clinic_channel_numbers``
    the routing table: it maps the number a patient dialled to the clinic
    that owns it, so it has to be readable *before* a tenant is known.

They hold no patient data and are protected by application-layer scoping.
"""
from __future__ import annotations

from django.db import migrations

#: Tenant tables whose ``clinic_id`` is always set.
RLS_TABLES = [
    # appointments
    "appointments",
    "appointment_events",
    "patients",
    "patient_consents",
    "reminder_logs",
    # doctors
    "doctors",
    "doctor_schedules",
    "doctor_schedule_exceptions",
    "doctor_status_events",
    "doctor_status_current",
    # conversations
    "conversations",
    "conversation_messages",
    "call_logs",
    "follow_up_tasks",
    "notification_logs",
    # tenancy
    "clinic_agent_configs",
    "provider_connections",
    # usage
    "usage_events",
    "clinic_subscriptions",
    # core
    "outbox_events",
    "idempotency_records",
]

#: Tenant tables that may additionally hold a platform-level row, i.e. a row
#: whose ``clinic_id`` is NULL (a login audit, a webhook we could not route).
RLS_TABLES_WITH_PLATFORM_ROWS = [
    "audit_logs",
    "provider_events",
]

_STRICT = (
    "clinic_id::text = current_setting('app.current_clinic_id', true)"
)
_PLATFORM_ROWS = (
    "clinic_id IS NULL OR "
    "clinic_id::text = current_setting('app.current_clinic_id', true)"
)


def _enable(table: str, predicate: str) -> list[str]:
    policy = f"{table}_tenant_isolation"
    return [
        f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;',
        f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;',
        f'CREATE POLICY "{policy}" ON "{table}" '
        f"USING ({predicate}) WITH CHECK ({predicate});",
    ]


def apply_rls(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in RLS_TABLES:
            for statement in _enable(table, _STRICT):
                cursor.execute(statement)
        for table in RLS_TABLES_WITH_PLATFORM_ROWS:
            for statement in _enable(table, _PLATFORM_ROWS):
                cursor.execute(statement)


def unapply_rls(apps, schema_editor):
    """Remove the policies from every table that has a ``clinic_id``."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relkind = 'r'
              AND EXISTS (
                  SELECT 1 FROM pg_attribute a
                  WHERE a.attrelid = c.oid
                    AND a.attname = 'clinic_id'
                    AND NOT a.attisdropped
              )
            """
        )
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(
                f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}";'
            )
            cursor.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY;')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;')


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_initial"),
        ("appointments", "0001_initial"),
        ("conversations", "0001_initial"),
        ("core", "0001_initial"),
        ("doctors", "0001_initial"),
        ("integrations", "0001_initial"),
        ("tenancy", "0001_initial"),
        ("usage", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(apply_rls, unapply_rls),
    ]
