"""Per-clinic provider secrets.

The table is created here, and the row-level security policy is applied
in the same migration.

It cannot be added to ``apps.core.migrations.0002_enable_rls``: that
migration runs *before* this one, so the table would not exist yet. The
policy is therefore applied here, with the same predicate the core
migration uses.
"""
from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


_STRICT = "clinic_id::text = current_setting('app.current_clinic_id', true)"


def apply_rls(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE "clinic_secrets" ENABLE ROW LEVEL SECURITY;')
        cursor.execute('ALTER TABLE "clinic_secrets" FORCE ROW LEVEL SECURITY;')
        cursor.execute(
            'CREATE POLICY "clinic_secrets_tenant_isolation" ON "clinic_secrets" '
            f"USING ({_STRICT}) WITH CHECK ({_STRICT});"
        )


def unapply_rls(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            'DROP POLICY IF EXISTS "clinic_secrets_tenant_isolation" ON "clinic_secrets";'
        )
        cursor.execute('ALTER TABLE "clinic_secrets" NO FORCE ROW LEVEL SECURITY;')
        cursor.execute('ALTER TABLE "clinic_secrets" DISABLE ROW LEVEL SECURITY;')


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0001_initial"),
        ("accounts", "0002_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClinicSecret",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        default=__import__("uuid").uuid4,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("key", models.CharField(max_length=100)),
                ("ciphertext", models.TextField()),
                ("fingerprint", models.CharField(blank=True, default="", max_length=40)),
                (
                    "clinic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s_set",
                        to="tenancy.clinic",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_clinic_secrets",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "db_table": "clinic_secrets",
                "indexes": [
                    models.Index(
                        fields=["clinic", "key"], name="clinic_secret_lookup_idx"
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("clinic", "key"), name="uniq_clinic_secret_key"
                    )
                ],
            },
        ),
        migrations.RunPython(apply_rls, unapply_rls),
    ]
