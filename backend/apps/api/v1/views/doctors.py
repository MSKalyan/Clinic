"""Doctor, schedule and availability endpoints."""
from __future__ import annotations

from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.api.v1.mixins import TenantScopedViewSet
from apps.api.v1.permissions import IsClinicAdmin, IsStaffMember
from apps.api.v1.serializers import (
    DoctorAvailabilitySerializer,
    DoctorScheduleExceptionSerializer,
    DoctorScheduleSerializer,
    DoctorSerializer,
    DoctorStatusCurrentSerializer,
    DoctorStatusEventSerializer,
    StatusEventCreateSerializer,
)
from apps.core.audit import record_audit
from apps.core.constants import AuditAction, Role
from apps.doctors.models import (
    STATUS_SOURCE_DASHBOARD,
    Doctor,
    DoctorSchedule,
    DoctorScheduleException,
    DoctorStatusCurrent,
    DoctorStatusEvent,
)
from apps.doctors.services.schedule import seed_default_schedule
from apps.doctors.services.status import DoctorStatusService


class DoctorViewSet(TenantScopedViewSet):
    """Doctors practising at the clinic."""

    model = Doctor
    serializer_class = DoctorSerializer
    permission_classes = [IsStaffMember]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        role = getattr(self.request, "clinic_role", "")
        if role == Role.DOCTOR.value:
            # A doctor sees their own profile plus colleagues' names.
            queryset = queryset.filter(
                Q(user_id=user.id) | Q(is_active=True)
            )
        if self.request.query_params.get("include_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        return queryset

    def get_permissions(self):
        if self.action in {"create", "destroy"}:
            return [IsClinicAdmin()]
        return super().get_permissions()

    def perform_create(self, serializer) -> None:
        doctor = serializer.save(clinic=self.get_clinic())
        # Without a schedule the doctor has zero bookable slots. Give them the
        # clinic's default working hours so they can be booked immediately.
        seed_default_schedule(doctor)
        record_audit(
            action=AuditAction.CREATE,
            resource_type="doctor",
            resource_id=doctor.id,
            clinic_id=doctor.clinic_id,
            actor=self.request.user,
            request=self.request,
        )

    @action(detail=True, methods=["get"], url_path="availability")
    def availability(self, request, pk=None):
        """The effective availability of a doctor right now."""
        doctor = self.get_object()
        snapshot = DoctorStatusService.get_current(doctor)
        return Response(DoctorAvailabilitySerializer(snapshot.as_dict()).data)

    @action(detail=True, methods=["get", "post"], url_path="availability-events")
    def availability_events(self, request, pk=None):
        """The immutable history of status changes."""
        doctor = self.get_object()
        if request.method == "POST":
            if getattr(request, "clinic_role", "") not in {
                Role.CLINIC_ADMIN.value,
                Role.DOCTOR.value,
            }:
                return Response(
                    {
                        "error": {
                            "code": "forbidden",
                            "message": "Only a doctor or clinic admin can update availability.",
                        }
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            if (
                getattr(request, "clinic_role", "") == Role.DOCTOR.value
                and doctor.user_id != request.user.id
            ):
                return Response(
                    {
                        "error": {
                            "code": "not_your_doctor",
                            "message": "You can only update your own availability.",
                        }
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            serializer = StatusEventCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            snapshot = DoctorStatusService.record(
                doctor=doctor,
                status=data["status"],
                source=data.get("source") or STATUS_SOURCE_DASHBOARD,
                actor=request.user,
                expected_arrival_at=data.get("expected_arrival_at"),
                expected_departure_at=data.get("expected_departure_at"),
                effective_from=data.get("effective_from"),
                effective_until=data.get("effective_until"),
                notes=data.get("notes", ""),
            )
            record_audit(
                action=AuditAction.STATUS_CHANGE,
                resource_type="doctor_status",
                resource_id=doctor.id,
                clinic_id=doctor.clinic_id,
                actor=request.user,
                request=request,
                metadata={"status": data["status"], "version": snapshot.version},
            )
            return Response(
                DoctorAvailabilitySerializer(snapshot.as_dict()).data,
                status=status.HTTP_201_CREATED,
            )

        events = DoctorStatusEvent.objects.filter(clinic=doctor.clinic_id, doctor=doctor)
        return Response(DoctorStatusEventSerializer(events, many=True).data)

    @action(detail=True, methods=["get"], url_path="status-history")
    def status_history(self, request, pk=None):
        doctor = self.get_object()
        events = DoctorStatusEvent.objects.filter(clinic=doctor.clinic_id, doctor=doctor)
        current = DoctorStatusCurrent.objects.filter(
            clinic=doctor.clinic_id, doctor=doctor
        ).first()
        return Response(
            {
                "current": (
                    DoctorStatusCurrentSerializer(current).data if current else None
                ),
                "events": DoctorStatusEventSerializer(events, many=True).data,
            }
        )

    @action(detail=True, methods=["get", "post"], url_path="schedules")
    def schedules(self, request, pk=None):
        doctor = self.get_object()
        if request.method == "POST":
            if getattr(request, "clinic_role", "") != Role.CLINIC_ADMIN.value:
                return Response(
                    {
                        "error": {
                            "code": "forbidden",
                            "message": "Only a clinic admin can edit the rota.",
                        }
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            serializer = DoctorScheduleSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(clinic=self.get_clinic(), doctor=doctor)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        schedules = DoctorSchedule.objects.filter(clinic=doctor.clinic_id, doctor=doctor)
        return Response(DoctorScheduleSerializer(schedules, many=True).data)

    @action(detail=True, methods=["get", "post"], url_path="schedule-exceptions")
    def schedule_exceptions(self, request, pk=None):
        doctor = self.get_object()
        if request.method == "POST":
            if getattr(request, "clinic_role", "") != Role.CLINIC_ADMIN.value:
                return Response(
                    {
                        "error": {
                            "code": "forbidden",
                            "message": "Only a clinic admin can edit schedule exceptions.",
                        }
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            serializer = DoctorScheduleExceptionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(clinic=self.get_clinic(), doctor=doctor)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        exceptions = DoctorScheduleException.objects.filter(
            clinic=doctor.clinic_id, doctor=doctor
        )
        return Response(DoctorScheduleExceptionSerializer(exceptions, many=True).data)
