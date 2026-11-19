/**
 * Types mirroring the Django REST API.
 *
 * These are hand-written rather than generated so that the dashboard has no
 * build-time dependency on the backend. The shapes match the serializers in
 * `backend/apps/api/v1/serializers.py`.
 */

export type Role = "clinic_admin" | "doctor" | "receptionist";

export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  phone: string;
  is_platform_admin: boolean;
}

export interface ClinicMembership {
  clinic_id: string;
  name: string;
  timezone: string;
  role: Role;
}

export interface TokenPair {
  access: string;
  refresh: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Doctor {
  id: string;
  name: string;
  slug: string;
  specialization: string;
  phone: string;
  languages: string[];
  is_active: boolean;
  sort_order: number;
  created_at?: string;
  updated_at?: string;
}

export interface DoctorStatusEvent {
  id: string;
  doctor: string;
  doctor_name: string;
  status: DoctorStatus;
  effective_from: string;
  effective_until: string | null;
  expected_arrival_at: string | null;
  expected_departure_at: string | null;
  source: string;
  updated_by: string | null;
  updated_by_identifier: string;
  notes: string;
  sequence: number;
  created_at: string;
}

export interface DoctorStatusCurrent {
  doctor: string;
  doctor_name: string;
  current_status: DoctorStatus;
  last_confirmed_at: string | null;
  expected_arrival_at: string | null;
  expected_departure_at: string | null;
  source: string;
  version: number;
  updated_at: string;
}

export type DoctorStatus =
  | "scheduled"
  | "present"
  | "running_late"
  | "unavailable"
  | "on_leave"
  | "finished_for_day"
  | "unknown";

export interface DoctorAvailability {
  doctor_id: string;
  status: DoctorStatus;
  recorded_status: DoctorStatus;
  is_stale: boolean;
  source: string;
  version: number;
  last_confirmed_at: string | null;
  effective_from: string | null;
  expected_arrival_at: string | null;
  expected_departure_at: string | null;
  notes: string;
}

export interface DashboardDoctorStatus {
  doctor_id: string;
  doctor_name: string;
  specialization: string;
  status: DoctorStatus;
  recorded_status: DoctorStatus;
  is_stale: boolean;
  last_confirmed_at: string | null;
  expected_arrival_at: string | null;
}

export interface Patient {
  id: string;
  name: string;
  phone: string;
  preferred_language: string;
  communication_preferences: Record<string, boolean>;
  notes: string;
  is_active: boolean;
}

export type AppointmentStatus =
  | "booked"
  | "confirmed"
  | "checked_in"
  | "completed"
  | "cancelled"
  | "no_show"
  | "reschedule_pending";

export interface Appointment {
  id: string;
  reference: string;
  doctor: string;
  doctor_name: string;
  patient: string;
  patient_name: string;
  patient_phone: string;
  start_at: string;
  end_at: string;
  status: AppointmentStatus;
  booking_source: string;
  notes: string;
  cancellation_reason: string;
  created_at: string;
  updated_at: string;
}

export interface Slot {
  doctor_id: string;
  doctor_name: string;
  specialization: string;
  start_at: string;
  end_at: string;
  local_date: string;
  display_start: string;
  display_end: string;
  doctor_status: DoctorStatus;
  status_is_stale: boolean;
  available: boolean;
  reason: string;
}

export interface FollowUpTask {
  id: string;
  patient: string | null;
  patient_name: string;
  related_appointment: string | null;
  conversation: string | null;
  task_type: string;
  priority: "low" | "normal" | "high" | "urgent";
  assigned_to: string | null;
  due_at: string | null;
  status: "open" | "in_progress" | "resolved" | "declined" | "not_required";
  resolution_reason: string;
  notes: string;
  attempts: number;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface PatientConsent {
  id: string;
  patient: string;
  purpose: string;
  channel: string;
  consent_status: string;
  captured_at: string;
  withdrawn_at: string | null;
  evidence_reference: string;
  notes: string;
}

export interface ConversationMessage {
  id: string;
  direction: string;
  message_type: string;
  excerpt: string;
  created_at: string;
}

export interface CallLog {
  id: string;
  conversation: string | null;
  provider_call_id: string;
  direction: string;
  from_number: string;
  to_number: string;
  duration_seconds: number;
  outcome: string;
  failure_reason: string;
  transcript_reference: string;
  recording_reference: string;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  patient: string | null;
  patient_name: string;
  patient_phone: string;
  channel: string;
  provider_conversation_id: string;
  status: string;
  language: string;
  summary: string;
  outcome: string;
  escalation_reason: string;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
}

export interface DashboardSummary {
  clinic: {
    id: string;
    name: string;
    timezone: string;
    status: string;
  };
  generated_at: string;
  appointments: {
    today_total: number;
    today_by_status: Record<string, number>;
    upcoming_7_days: number;
    cancelled_today: number;
    no_show_today: number;
  };
  doctors: {
    total: number;
    status: DashboardDoctorStatus[];
    stale_count: number;
  };
  calls: {
    total_7_days: number;
    unresolved_7_days: number;
    by_outcome: Record<string, number>;
  };
  conversations: {
    open: number;
    escalated: number;
  };
  tasks: {
    open: number;
    in_progress: number;
    overdue: number;
  };
  reminders: {
    pending: number;
    failed: number;
    delivered: number;
  };
  usage: {
    [key: string]: unknown;
  };
}

export type ConfigKeyStatus = "set" | "platform" | "missing";

export interface ConfigKey {
  key: string;
  label: string;
  purpose: string;
  group: string;
  group_label: string;
  scope: "clinic" | "platform";
  required: boolean;
  secret: boolean;
  env_var: string;
  status: ConfigKeyStatus;
  is_set: boolean;
  source: "clinic" | "platform" | "";
  fingerprint: string;
  updated_at: string | null;
  editable: boolean;
}

export interface ConfigGroup {
  key: string;
  label: string;
  keys: string[];
}

export interface ClinicConfiguration {
  clinic_id: string;
  keys: ConfigKey[];
  groups: ConfigGroup[];
  summary: {
    total: number;
    set: number;
    platform: number;
    missing: number;
    missing_required: number;
  };
}
