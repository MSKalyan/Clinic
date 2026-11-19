"""Patient lifecycle messages (currently the welcome text)."""
from __future__ import annotations

import logging
from typing import Any

from apps.conversations.services.templates import render_template
from apps.core.constants import Channel, ConsentPurpose
from apps.core.exceptions import ConsentRequired, OptedOut
from apps.core.rls import rls_scope

logger = logging.getLogger("apps.appointments.patient_messages")


def welcome_body(patient: Any) -> str:
    return render_template(
        "welcome",
        {
            "patient_name": patient.name or "there",
            "clinic_name": patient.clinic.name,
            "phone": patient.phone,
            "timezone": patient.clinic.timezone or "local time",
        },
    )


def send_welcome_message(patient_id: str, *, clinic_id: str) -> Any | None:
    """Queue the one-time welcome text for a newly created patient."""
    from apps.appointments.models import Patient
    from apps.conversations.services.notifications import NotificationService
    from apps.realtime.broadcast import dashboard_changed

    with rls_scope(clinic_id):
        try:
            patient = Patient.objects.select_related("clinic").get(pk=patient_id)
        except Patient.DoesNotExist:  # pragma: no cover - deleted immediately
            return None
        try:
            log = NotificationService.send(
                clinic=patient.clinic,
                patient=patient,
                channel=Channel.WHATSAPP,
                template_id="welcome",
                body=welcome_body(patient),
                purpose=ConsentPurpose.APPOINTMENT_TRANSACTIONAL,
                idempotency_key=f"welcome:{patient.pk}",
                payload={"source": "patient_created"},
            )
        except (ConsentRequired, OptedOut) as exc:
            logger.info("welcome message skipped for %s: %s", patient.pk, exc)
            return None
        except Exception:  # pragma: no cover - defensive
            logger.exception("could not queue welcome message for %s", patient.pk)
            return None

    dashboard_changed(clinic_id, "patient", patient_id=str(patient_id))
    return log


def queue_welcome_message(patient: Any) -> None:
    """Register the welcome text after the patient row is committed."""
    from django.db import transaction

    clinic_id = str(patient.clinic_id)
    patient_id = str(patient.pk)
    transaction.on_commit(
        lambda: send_welcome_message(patient_id, clinic_id=clinic_id)
    )
