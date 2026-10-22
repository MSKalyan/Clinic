"""Conflict guards: no two overlapping appointments for the same doctor.

The booking service already re-checks availability inside the transaction
and locks the doctor row, so two simultaneous requests serialise. This
constraint is the *last* line of defence: even a bug in the service layer
(a missing filter, a race in a different code path, a direct ORM write)
cannot produce two appointments that occupy the same doctor at the same
time.

``EXCLUDE USING gist`` with a ``tstzrange`` expresses "these two rows must
not overlap" declaratively. ``btree_gist`` is required so that the plain
``uuid`` equality on ``doctor_id`` can be part of a GiST index.

Only the statuses that actually occupy a slot are covered: a cancelled,
completed or no-show appointment frees its slot, so it must not block a
new booking.

The ten-minute buffer between appointments is a *per-clinic policy* and is
therefore enforced by the availability service rather than by the
constraint, which always uses the true appointment interval.
"""
from __future__ import annotations

from django.db import migrations

CONSTRAINT_NAME = "appointments_no_doctor_overlap"

OCCUPYING_STATUSES = ("booked", "confirmed", "checked_in", "reschedule_pending")


def _predicate() -> str:
    statuses = ", ".join(f"'{status}'" for status in OCCUPYING_STATUSES)
    return f"status IN ({statuses})"


def apply_conflict_guards(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        # ``btree_gist`` is a trusted extension, so a non-superuser that owns
        # the database may install it.
        cursor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")
        cursor.execute(
            f"ALTER TABLE appointments ADD CONSTRAINT {CONSTRAINT_NAME} "
            "EXCLUDE USING gist ("
            "doctor_id WITH =, "
            "tstzrange(start_at, end_at) WITH &&"
            f") WHERE ({_predicate()});"
        )


def unapply_conflict_guards(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME};"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("appointments", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        migrations.RunPython(apply_conflict_guards, unapply_conflict_guards),
    ]
