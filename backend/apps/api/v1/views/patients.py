"""Patient endpoints."""
from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.api.v1.mixins import TenantScopedViewSet
from apps.api.v1.permissions import IsStaffMember
from apps.api.v1.serializers import (
    AppointmentSerializer,
    CommunicationPreferenceSerializer,
    PatientConsentSerializer,
    PatientSerializer,
)
from apps.appointments.models import Appointment, Patient
from apps.core.audit import record_audit
from apps.core.constants import AuditAction


class PatientViewSet(TenantScopedViewSet):
    """Patients of the active clinic."""

    model = Patient
    serializer_class = PatientSerializer
    permission_classes = [IsStaffMember]

    def get_queryset(self):
        queryset = super().get_queryset().order_by("name")
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        phone = self.request.query_params.get("phone")
        if phone:
            from apps.core.utils import normalise_phone

            queryset = queryset.filter(phone=normalise_phone(phone))
        return queryset

    def perform_create(self, serializer) -> None:
        from apps.appointments.services.patient_messages import queue_welcome_message

        patient = serializer.save(clinic=self.get_clinic())
        queue_welcome_message(patient)
        record_audit(
            action=AuditAction.CREATE,
            resource_type="patient",
            resource_id=patient.id,
            clinic_id=patient.clinic_id,
            actor=self.request.user,
            request=self.request,
        )

    @action(detail=True, methods=["get"], url_path="appointments")
    def appointments(self, request, pk=None):  # noqa: ANN001
        patient = self.get_object()
        appointments = (
            Appointment.objects.filter(clinic=patient.clinic_id, patient=patient)
            .select_related("doctor", "patient")
            .order_by("-start_at")
        )
        return Response(AppointmentSerializer(appointments, many=True).data)

    @action(detail=True, methods=["post"], url_path="communication-preferences")
    def communication_preferences(self, request, pk=None):  # noqa: ANN001
        patient = self.get_object()
        serializer = CommunicationPreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient = serializer.update(patient)
        record_audit(
            action=AuditAction.UPDATE,
            resource_type="patient_preferences",
            resource_id=patient.id,
            clinic_id=patient.clinic_id,
            actor=request.user,
            request=request,
            metadata={"channel": serializer.validated_data["channel"]},
        )
        return Response(PatientSerializer(patient).data)

    @action(detail=True, methods=["get", "post"], url_path="consents")
    def consents(self, request, pk=None):  # noqa: ANN001
        patient = self.get_object()
        if request.method == "POST":
            serializer = PatientConsentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(clinic=self.get_clinic(), patient=patient)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        consents = patient.consents.all()
        return Response(PatientConsentSerializer(consents, many=True).data)
