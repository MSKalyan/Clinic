"""Dashboard summary endpoint.

One call returns the operational picture the PRD asks for in section 5.7.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.v1.base import TenantAwareAPIView
from apps.api.v1.permissions import IsStaffMember
from apps.appointments.models import Appointment
from apps.conversations.models import CallLog, Conversation, FollowUpTask, NotificationLog
from apps.core.constants import ConversationStatus, DeliveryStatus, TaskStatus
from apps.doctors.models import Doctor
from apps.doctors.services.status import DoctorStatusService
from apps.usage.services import UsageMeter


class DashboardSummaryView(TenantAwareAPIView):
    """Today's operational summary for the active clinic."""

    permission_classes = [IsAuthenticated, IsStaffMember]

    def get(self, request):  # noqa: ANN001
        clinic = getattr(request, "clinic", None)
        if clinic is None:
            return Response(
                {"error": {"code": "no_clinic", "message": "No clinic selected."}}, status=403
            )

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        appointments = Appointment.objects.filter(clinic=clinic)
        todays = appointments.filter(start_at__gte=today_start, start_at__lt=today_end)

        doctors = list(
            Doctor.objects.filter(clinic=clinic, is_active=True).select_related("clinic")
        )
        doctor_status = []
        stale_count = 0
        for doctor in doctors:
            snapshot = DoctorStatusService.get_current(doctor)
            if snapshot.is_stale:
                stale_count += 1
            doctor_status.append(
                {
                    "doctor_id": str(doctor.id),
                    "doctor_name": doctor.name,
                    "specialization": doctor.specialization,
                    "status": snapshot.status,
                    "recorded_status": snapshot.recorded_status,
                    "is_stale": snapshot.is_stale,
                    "last_confirmed_at": (
                        snapshot.last_confirmed_at.isoformat() if snapshot.last_confirmed_at else None
                    ),
                    "expected_arrival_at": (
                        snapshot.expected_arrival_at.isoformat()
                        if snapshot.expected_arrival_at
                        else None
                    ),
                }
            )

        calls = CallLog.objects.filter(clinic=clinic)
        conversations = Conversation.objects.filter(clinic=clinic)

        payload = {
            "clinic": {
                "id": str(clinic.id),
                "name": clinic.name,
                "timezone": clinic.timezone,
                "status": clinic.status,
            },
            "generated_at": now.isoformat(),
            "appointments": {
                "today_total": todays.count(),
                "today_by_status": {
                    row["status"]: row["count"]
                    for row in todays.values("status").annotate(count=Count("id"))
                },
                "upcoming_7_days": appointments.filter(
                    start_at__gte=now, start_at__lte=now + timedelta(days=7)
                ).count(),
                "cancelled_today": todays.filter(status="cancelled").count(),
                "no_show_today": todays.filter(status="no_show").count(),
            },
            "doctors": {
                "total": len(doctors),
                "status": doctor_status,
                "stale_count": stale_count,
            },
            "calls": {
                "total_7_days": calls.filter(
                    created_at__gte=now - timedelta(days=7)
                ).count(),
                "unresolved_7_days": calls.filter(
                    created_at__gte=now - timedelta(days=7),
                    outcome__in=["unresolved", "abandoned", "escalated"],
                ).count(),
                "by_outcome": {
                    row["outcome"]: row["count"]
                    for row in calls.filter(created_at__gte=now - timedelta(days=7))
                    .values("outcome")
                    .annotate(count=Count("id"))
                    if row["outcome"]
                },
            },
            "conversations": {
                "open": conversations.filter(status=ConversationStatus.OPEN).count(),
                "escalated": conversations.filter(status=ConversationStatus.ESCALATED).count(),
            },
            "tasks": {
                "open": FollowUpTask.objects.filter(
                    clinic=clinic, status=TaskStatus.OPEN
                ).count(),
                "in_progress": FollowUpTask.objects.filter(
                    clinic=clinic, status=TaskStatus.IN_PROGRESS
                ).count(),
                "overdue": FollowUpTask.objects.filter(
                    clinic=clinic,
                    status__in=[TaskStatus.OPEN, TaskStatus.IN_PROGRESS],
                    due_at__lt=now,
                ).count(),
            },
            "reminders": {
                "pending": NotificationLog.objects.filter(
                    clinic=clinic, delivery_status=DeliveryStatus.QUEUED
                ).count(),
                "failed": NotificationLog.objects.filter(
                    clinic=clinic, delivery_status=DeliveryStatus.FAILED
                ).count(),
                "delivered": NotificationLog.objects.filter(
                    clinic=clinic,
                    delivery_status__in=[DeliveryStatus.DELIVERED, DeliveryStatus.READ],
                ).count(),
            },
            "usage": UsageMeter.summarise(clinic, since=now - timedelta(days=30)),
        }
        return Response(payload)
