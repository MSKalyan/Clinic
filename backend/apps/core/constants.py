"""Shared domain constants.

Keeping these in one place avoids stringly-typed drift between models,
services, serializers and the AI tool layer.
"""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Roles a user can hold *within a clinic*."""

    CLINIC_ADMIN = "clinic_admin"
    DOCTOR = "doctor"
    RECEPTIONIST = "receptionist"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


class ClinicStatus(StrEnum):
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    OFFBOARDED = "offboarded"


class DoctorStatus(StrEnum):
    """Operational status of a doctor at a point in time.

    ``present`` is an explicit operational assertion by an authorised human or
    integration. It is *not* proof of physical location (PRD 5.2).
    """

    SCHEDULED = "scheduled"
    PRESENT = "present"
    RUNNING_LATE = "running_late"
    UNAVAILABLE = "unavailable"
    ON_LEAVE = "on_leave"
    FINISHED_FOR_DAY = "finished_for_day"
    UNKNOWN = "unknown"


#: Statuses that explicitly mean "do not offer this doctor right now".
BLOCKING_STATUSES = frozenset(
    {
        DoctorStatus.ON_LEAVE,
        DoctorStatus.UNAVAILABLE,
        DoctorStatus.FINISHED_FOR_DAY,
    }
)

#: Statuses that mean the doctor is physically at the clinic.
PRESENT_STATUSES = frozenset({DoctorStatus.PRESENT, DoctorStatus.RUNNING_LATE})


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    RESCHEDULE_PENDING = "reschedule_pending"


#: Statuses that occupy a slot and therefore block a double booking.
OCCUPYING_STATUSES = frozenset(
    {
        AppointmentStatus.BOOKED,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CHECKED_IN,
        AppointmentStatus.RESCHEDULE_PENDING,
    }
)

#: Allowed appointment status transitions (PRD 5.3).
APPOINTMENT_TRANSITIONS: dict[AppointmentStatus, frozenset[AppointmentStatus]] = {
    AppointmentStatus.BOOKED: frozenset(
        {
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.CANCELLED,
            AppointmentStatus.RESCHEDULE_PENDING,
            AppointmentStatus.NO_SHOW,
            AppointmentStatus.COMPLETED,
        }
    ),
    AppointmentStatus.CONFIRMED: frozenset(
        {
            AppointmentStatus.CHECKED_IN,
            AppointmentStatus.CANCELLED,
            AppointmentStatus.RESCHEDULE_PENDING,
            AppointmentStatus.NO_SHOW,
            AppointmentStatus.COMPLETED,
        }
    ),
    AppointmentStatus.RESCHEDULE_PENDING: frozenset(
        {
            AppointmentStatus.BOOKED,
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.CANCELLED,
        }
    ),
    AppointmentStatus.CHECKED_IN: frozenset({AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW}),
    AppointmentStatus.COMPLETED: frozenset(),
    AppointmentStatus.CANCELLED: frozenset(),
    AppointmentStatus.NO_SHOW: frozenset(),
}


class BookingSource(StrEnum):
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    DASHBOARD = "dashboard"
    API = "api"
    AGENT = "agent"


class Channel(StrEnum):
    VOICE = "voice"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    DASHBOARD = "dashboard"


class ConversationStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"
    TAKEN_OVER = "taken_over"


class CallOutcome(StrEnum):
    RESOLVED = "resolved"
    BOOKED = "booked"
    ESCALATED = "escalated"
    UNRESOLVED = "unresolved"
    ABANDONED = "abandoned"
    FAILED = "failed"
    OUT_OF_HOURS = "out_of_hours"


class FollowUpTaskType(StrEnum):
    MISSED_CALL = "missed_call"
    UNRESOLVED_REQUEST = "unresolved_request"
    DELAY_NOTIFICATION = "delay_notification"
    LEAVE_RESCHEDULE = "leave_reschedule"
    REMINDER_FAILED = "reminder_failed"
    HUMAN_ASSISTANCE = "human_assistance"


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DECLINED = "declined"
    NOT_REQUIRED = "not_required"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ConsentStatus(StrEnum):
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"
    PENDING = "pending"


class ConsentPurpose(StrEnum):
    APPOINTMENT_TRANSACTIONAL = "appointment_transactional"
    REMINDERS = "reminders"
    MARKETING = "marketing"
    CARE_FOLLOW_UP = "care_follow_up"


class ProviderType(StrEnum):
    VOICE = "voice"
    MESSAGING = "messaging"
    TELEPHONY = "telephony"


class AccountMode(StrEnum):
    SHARED = "shared"
    DEDICATED = "dedicated"


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ERROR = "error"


class InternalEventType(StrEnum):
    """Internal domain events emitted through the transactional outbox."""

    APPOINTMENT_BOOKED = "AppointmentBooked"
    APPOINTMENT_RESCHEDULED = "AppointmentRescheduled"
    APPOINTMENT_CANCELLED = "AppointmentCancelled"
    DOCTOR_STATUS_CHANGED = "DoctorStatusChanged"
    REMINDER_DUE = "ReminderDue"
    CALL_UNRESOLVED = "CallUnresolved"
    NOTIFICATION_FAILED = "NotificationFailed"
    FOLLOW_UP_CREATED = "FollowUpCreated"


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    STATUS_CHANGE = "status_change"
    BOOK = "book"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    LOGIN = "login"
    ESCALATE = "escalate"
    RESOLVE = "resolve"
    EXPORT = "export"
    ACCESS = "access"
