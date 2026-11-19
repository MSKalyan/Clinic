"""Serializers for the v1 API."""
from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import ClinicMembership, User
from apps.appointments.models import Appointment, Patient, PatientConsent
from apps.conversations.models import CallLog, Conversation, FollowUpTask, NotificationLog
from apps.core.utils import normalise_phone
from apps.doctors.models import (
    Doctor,
    DoctorSchedule,
    DoctorScheduleException,
    DoctorStatusCurrent,
    DoctorStatusEvent,
)
from apps.tenancy.models import (
    Clinic,
    ClinicAgentConfig,
    ClinicChannelNumber,
    ClinicSettings,
    ProviderConnection,
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "phone", "is_platform_admin"]
        read_only_fields = ["id", "is_platform_admin"]


# ---------------------------------------------------------------------------
# Clinics and membership
# ---------------------------------------------------------------------------
class ClinicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clinic
        fields = [
            "id",
            "name",
            "slug",
            "timezone",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ClinicSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicSettings
        fields = [
            "operating_hours",
            "default_language",
            "supported_languages",
            "appointment_rules",
            "reminder_policy",
            "escalation_policy",
            "status_freshness_minutes",
            "privacy_notice_url",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class ClinicAgentConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicAgentConfig
        fields = [
            "id",
            "name",
            "greeting",
            "agent_instructions",
            "enabled_channels",
            "voice_language",
            "configuration_version",
            "status",
            "is_default",
        ]
        read_only_fields = ["id", "configuration_version"]


class ProviderConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderConnection
        fields = [
            "id",
            "provider_type",
            "account_mode",
            "external_account_id",
            "status",
            "display_name",
            "config",
            "last_error",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        # ``secret_reference`` is deliberately write-only and never returned:
        # cross-tenant credentials must not be retrievable through the API.
        extra_kwargs = {"secret_reference": {"write_only": True}}


class ClinicChannelNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicChannelNumber
        fields = [
            "id",
            "channel",
            "provider_connection",
            "external_number_id",
            "display_number",
            "routing_status",
            "capabilities",
        ]
        read_only_fields = ["id"]


class MembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.get_full_name", read_only=True)

    class Meta:
        model = ClinicMembership
        fields = [
            "id",
            "user",
            "user_email",
            "user_name",
            "role",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class MembershipCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=["clinic_admin", "doctor", "receptionist"]
    )

    def create(self, validated_data):
        email = validated_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise serializers.ValidationError(
                {"email": "No user with that email exists. Create the user first."}
            )
        membership, created = ClinicMembership.objects.get_or_create(
            clinic=self.context["clinic"],
            user=user,
            defaults={"role": validated_data["role"], "status": "active"},
        )
        return membership


# ---------------------------------------------------------------------------
# Doctors
# ---------------------------------------------------------------------------
class DoctorSerializer(serializers.ModelSerializer):
    """Doctors with an auto-generated, clinic-unique slug.

    The slug used to be read-only without ever being generated. That meant the
    first doctor got an empty slug and every later one violated the unique
    ``(clinic, slug)`` constraint -- which is why newly added doctors never
    showed up. The slug is now derived from the name and made unique per clinic.
    """

    slug = serializers.SlugField(max_length=120, required=False, allow_blank=True)

    class Meta:
        model = Doctor
        fields = [
            "id",
            "name",
            "slug",
            "specialization",
            "phone",
            "languages",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def _unique_slug(self, name: str, clinic, exclude_pk=None) -> str:
        from django.utils.text import slugify

        base = slugify(name) or "doctor"
        slug = base
        counter = 2
        while (
            Doctor.objects.filter(clinic=clinic, slug=slug)
            .exclude(pk=exclude_pk)
            .exists()
        ):
            slug = f"{base}-{counter}"
            counter += 1
        return slug

    def create(self, validated_data):  # noqa: ANN003
        clinic = validated_data.get("clinic") or self.context.get("clinic")
        validated_data.setdefault("slug", self._unique_slug(validated_data["name"], clinic))
        return super().create(validated_data)

    def update(self, instance, validated_data):  # noqa: ANN003
        if "name" in validated_data and not validated_data.get("slug"):
            validated_data["slug"] = self._unique_slug(
                validated_data["name"], instance.clinic, exclude_pk=instance.pk
            )
        return super().update(instance, validated_data)


class DoctorScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoctorSchedule
        fields = [
            "id",
            "doctor",
            "weekday",
            "start_time",
            "end_time",
            "effective_from",
            "effective_until",
            "slot_interval_minutes",
            "is_active",
        ]
        read_only_fields = ["id"]


class DoctorScheduleExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoctorScheduleException
        fields = [
            "id",
            "doctor",
            "date",
            "start_time",
            "end_time",
            "kind",
            "reason",
        ]
        read_only_fields = ["id"]


class DoctorStatusEventSerializer(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source="doctor.name", read_only=True)

    class Meta:
        model = DoctorStatusEvent
        fields = [
            "id",
            "doctor",
            "doctor_name",
            "status",
            "effective_from",
            "effective_until",
            "expected_arrival_at",
            "expected_departure_at",
            "source",
            "updated_by",
            "updated_by_identifier",
            "notes",
            "sequence",
            "created_at",
        ]
        read_only_fields = fields


class DoctorStatusCurrentSerializer(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source="doctor.name", read_only=True)

    class Meta:
        model = DoctorStatusCurrent
        fields = [
            "doctor",
            "doctor_name",
            "current_status",
            "last_confirmed_at",
            "expected_arrival_at",
            "expected_departure_at",
            "source",
            "version",
            "updated_at",
        ]
        read_only_fields = fields


class DoctorAvailabilitySerializer(serializers.Serializer):
    """The effective availability of a doctor (status + schedule)."""

    doctor_id = serializers.CharField()
    doctor_name = serializers.CharField()
    status = serializers.CharField()
    recorded_status = serializers.CharField()
    is_stale = serializers.BooleanField()
    last_confirmed_at = serializers.DateTimeField(allow_null=True)
    expected_arrival_at = serializers.DateTimeField(allow_null=True)
    expected_departure_at = serializers.DateTimeField(allow_null=True)
    source = serializers.CharField()
    version = serializers.IntegerField()


class StatusEventCreateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            "scheduled",
            "present",
            "running_late",
            "unavailable",
            "on_leave",
            "finished_for_day",
            "unknown",
        ]
    )
    expected_arrival_at = serializers.DateTimeField(required=False, allow_null=True)
    expected_departure_at = serializers.DateTimeField(required=False, allow_null=True)
    effective_from = serializers.DateTimeField(required=False, allow_null=True)
    effective_until = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)
    source = serializers.CharField(required=False, max_length=30)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = [
            "id",
            "name",
            "phone",
            "preferred_language",
            "communication_preferences",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_phone(self, value: str) -> str:
        normalised = normalise_phone(value)
        if not normalised:
            raise serializers.ValidationError("Enter a valid phone number.")
        return normalised


class PatientConsentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientConsent
        fields = [
            "id",
            "patient",
            "purpose",
            "channel",
            "consent_status",
            "captured_at",
            "withdrawn_at",
            "evidence_reference",
            "notes",
        ]
        read_only_fields = ["id", "captured_at"]


class CommunicationPreferenceSerializer(serializers.Serializer):
    """Update the patient's channel preferences (opt-outs)."""

    channel = serializers.ChoiceField(choices=["sms", "whatsapp", "voice"])
    opt_out = serializers.BooleanField()
    preferred_language = serializers.CharField(required=False, allow_blank=True)

    def update(self, instance: Patient) -> Patient:
        channel = self.validated_data["channel"]
        preferences = dict(instance.communication_preferences or {})
        preferences[f"opt_out_{channel}"] = self.validated_data["opt_out"]
        instance.communication_preferences = preferences
        if self.validated_data.get("preferred_language"):
            instance.preferred_language = self.validated_data["preferred_language"]
        instance.save(
            update_fields=["communication_preferences", "preferred_language", "updated_at"]
        )
        return instance


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
class AppointmentSerializer(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source="doctor.name", read_only=True)
    patient_name = serializers.CharField(source="patient.name", read_only=True)
    patient_phone = serializers.CharField(source="patient.phone", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "reference",
            "doctor",
            "doctor_name",
            "patient",
            "patient_name",
            "patient_phone",
            "start_at",
            "end_at",
            "status",
            "booking_source",
            "notes",
            "cancellation_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "reference",
            "status",
            "booking_source",
            "cancellation_reason",
            "created_at",
            "updated_at",
        ]


class AppointmentCreateSerializer(serializers.Serializer):
    doctor = serializers.UUIDField()
    patient = serializers.UUIDField()
    start_at = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(required=False, min_value=5, max_value=240)
    notes = serializers.CharField(required=False, allow_blank=True)
    booking_source = serializers.CharField(required=False, default="dashboard")


class RescheduleSerializer(serializers.Serializer):
    start_at = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(required=False, min_value=5, max_value=240)
    notes = serializers.CharField(required=False, allow_blank=True)


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)
    force = serializers.BooleanField(required=False, default=False)


class SlotSerializer(serializers.Serializer):
    doctor_id = serializers.CharField()
    doctor_name = serializers.CharField()
    specialization = serializers.CharField(allow_blank=True)
    start_at = serializers.DateTimeField()
    end_at = serializers.DateTimeField()
    local_date = serializers.CharField()
    display_start = serializers.CharField()
    display_end = serializers.CharField()
    doctor_status = serializers.CharField()
    status_is_stale = serializers.BooleanField()
    available = serializers.BooleanField()
    reason = serializers.CharField(allow_blank=True)


# ---------------------------------------------------------------------------
# Conversations and tasks
# ---------------------------------------------------------------------------
class ConversationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.name", read_only=True, default="")
    patient_phone = serializers.CharField(source="patient.phone", read_only=True, default="")

    class Meta:
        model = Conversation
        fields = [
            "id",
            "patient",
            "patient_name",
            "patient_phone",
            "channel",
            "provider_conversation_id",
            "status",
            "language",
            "summary",
            "outcome",
            "escalation_reason",
            "taken_over_by",
            "started_at",
            "ended_at",
            "created_at",
        ]
        read_only_fields = fields


class CallLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = CallLog
        fields = [
            "id",
            "conversation",
            "provider_call_id",
            "direction",
            "from_number",
            "to_number",
            "duration_seconds",
            "outcome",
            "failure_reason",
            "started_at",
            "ended_at",
            "created_at",
        ]
        read_only_fields = fields


class FollowUpTaskSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.name", read_only=True)

    class Meta:
        model = FollowUpTask
        fields = [
            "id",
            "patient",
            "patient_name",
            "related_appointment",
            "conversation",
            "task_type",
            "priority",
            "assigned_to",
            "due_at",
            "status",
            "resolution_reason",
            "notes",
            "attempts",
            "created_at",
            "updated_at",
            "resolved_at",
        ]
        read_only_fields = ["id", "attempts", "created_at", "updated_at", "resolved_at"]


class FollowUpTaskUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["open", "in_progress", "resolved", "declined", "not_required"],
        required=False,
    )
    priority = serializers.ChoiceField(
        choices=["low", "normal", "high", "urgent"], required=False
    )
    assigned_to = serializers.UUIDField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class ResolveTaskSerializer(serializers.Serializer):
    resolution_reason = serializers.CharField(required=False, allow_blank=True, max_length=255)
    notes = serializers.CharField(required=False, allow_blank=True)


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = [
            "id",
            "patient",
            "appointment",
            "channel",
            "template_id",
            "provider_message_id",
            "delivery_status",
            "attempt_count",
            "last_error",
            "sent_at",
            "delivered_at",
            "created_at",
        ]
        read_only_fields = fields
