"""Appointment and availability-slot endpoints."""
from __future__ import annotations

from datetime import date

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.api.v1.base import TenantAwareViewSet
from apps.api.v1.mixins import TenantScopedViewSet
from apps.api.v1.permissions import IsStaffMember
from apps.api.v1.serializers import (
    AppointmentCreateSerializer,
    AppointmentSerializer,
    CancelSerializer,
    RescheduleSerializer,
    SlotSerializer,
)
from apps.appointments.models import Appointment, Patient
from apps.appointments.services.availability import AvailabilityService
from apps.appointments.services.booking import BookingService
from apps.core.audit import record_audit
from apps.core.constants import AuditAction, BookingSource
from apps.doctors.models import Doctor


class AppointmentViewSet(TenantScopedViewSet):
    """Appointments for the active clinic."""

    model = Appointment
    serializer_class = AppointmentSerializer
    permission_classes = [IsStaffMember]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("doctor", "patient")
            .order_by("start_at")
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("doctor"):
            queryset = queryset.filter(doctor_id=params["doctor"])
        if params.get("from"):
            queryset = queryset.filter(start_at__gte=params["from"])
        if params.get("to"):
            queryset = queryset.filter(start_at__lte=params["to"])
        return queryset

    def create(self, request, *args, **kwargs):
        """Book through the booking service so conflicts are impossible."""
        serializer = AppointmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        clinic = self.get_clinic()
        doctor = Doctor.objects.filter(clinic=clinic, pk=data["doctor"], is_active=True).first()
        if doctor is None:
            return Response(
                {"error": {"code": "doctor_not_found", "message": "That doctor is not available."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        patient = Patient.objects.filter(clinic=clinic, pk=data["patient"]).first()
        if patient is None:
            return Response(
                {"error": {"code": "patient_not_found", "message": "That patient was not found."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        appointment = BookingService.book(
            clinic=clinic,
            doctor=doctor,
            patient=patient,
            start_at=data["start_at"],
            source=data.get("booking_source") or BookingSource.DASHBOARD,
            duration_minutes=data.get("duration_minutes"),
            notes=data.get("notes", ""),
            actor=request.user,
            actor_type="staff",
        )
        record_audit(
            action=AuditAction.BOOK,
            resource_type="appointment",
            resource_id=appointment.id,
            clinic_id=clinic.id,
            actor=request.user,
            request=request,
            metadata={"reference": appointment.reference},
        )
        return Response(
            AppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):  # noqa: ANN001
        appointment = self.get_object()
        serializer = RescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        appointment = BookingService.reschedule(
            appointment=appointment,
            new_start_at=data["start_at"],
            actor=request.user,
            actor_type="staff",
            duration_minutes=data.get("duration_minutes"),
            notes=data.get("notes", ""),
        )
        record_audit(
            action=AuditAction.RESCHEDULE,
            resource_type="appointment",
            resource_id=appointment.id,
            clinic_id=appointment.clinic_id,
            actor=request.user,
            request=request,
            metadata={"reference": appointment.reference},
        )
        return Response(AppointmentSerializer(appointment).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):  # noqa: ANN001
        appointment = self.get_object()
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        appointment = BookingService.cancel(
            appointment=appointment,
            reason=data.get("reason", ""),
            actor=request.user,
            actor_type="staff",
            force=data.get("force", False),
        )
        record_audit(
            action=AuditAction.CANCEL,
            resource_type="appointment",
            resource_id=appointment.id,
            clinic_id=appointment.clinic_id,
            actor=request.user,
            request=request,
            metadata={"reference": appointment.reference, "reason": data.get("reason", "")},
        )
        return Response(AppointmentSerializer(appointment).data)


class AvailabilitySlotView(TenantAwareViewSet):
    """Bookable slots, computed from the live rota and existing bookings."""

    permission_classes = [IsStaffMember]

    def list(self, request):  # noqa: ANN001
        clinic = getattr(request, "clinic", None)
        if clinic is None:
            return Response({"error": {"code": "no_clinic", "message": "No clinic selected."}}, status=403)

        params = request.query_params
        doctors = None
        if params.get("doctor"):
            doctors = Doctor.objects.filter(
                clinic=clinic, pk=params["doctor"], is_active=True
            )
        elif params.get("specialization"):
            doctors = Doctor.objects.filter(
                clinic=clinic,
                specialization__icontains=params["specialization"],
                is_active=True,
            )

        on_date = None
        if params.get("date"):
            try:
                on_date = date.fromisoformat(params["date"][:10])
            except ValueError:
                return Response(
                    {
                        "error": {
                            "code": "invalid_date",
                            "message": "Use the format YYYY-MM-DD for the date.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        service = AvailabilityService(clinic)
        slots = service.slots(doctors=doctors, on_date=on_date)
        return Response(
            {
                "count": len(slots),
                "results": SlotSerializer(slots, many=True).data,
            }
        )
