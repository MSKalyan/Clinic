"""Store the appointment start a reminder was scheduled for.

The reminder used to derive that start from ``due_at + offset_hours``.
``due_at`` is a scheduling field, though: a retry or a sweep may move it,
and deriving the appointment time from it made a perfectly good reminder
look like it referred to a time the appointment no longer had.

The column is added as nullable, backfilled with the value the derivation
would have produced, and then made mandatory.
"""
from __future__ import annotations

from django.db import migrations, models
from django.db.models import F


def backfill_scheduled_start(apps, schema_editor):
    ReminderLog = apps.get_model("appointments", "ReminderLog")
    for reminder in ReminderLog.objects.all().iterator(chunk_size=500):
        reminder.scheduled_start_at = reminder.due_at + reminder.offset_hours * 3600
        reminder.save(update_fields=["scheduled_start_at"])


def noop(apps, schema_editor):
    """Nothing to undo -- the column is dropped by the reverse migration."""
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("appointments", "0002_appointments_conflict_guards"),
    ]

    operations = [
        migrations.AddField(
            model_name="reminderlog",
            name="scheduled_start_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(backfill_scheduled_start, noop),
        migrations.AlterField(
            model_name="reminderlog",
            name="scheduled_start_at",
            field=models.DateTimeField(),
        ),
    ]
