/**
 * Formatting helpers.
 *
 * Every timestamp the API returns is UTC ISO-8601. The clinic's timezone is
 * what a human at the clinic reads, so all displayed times go through the
 * clinic's zone -- not the browser's.
 */
import type { AppointmentStatus, DoctorStatus } from "./types";

/** Today's date as YYYY-MM-DD, in a clinic's timezone (or the browser's). */
export function todayIso(timezone?: string): string {
  if (timezone) {
    try {
      return new Intl.DateTimeFormat("en-CA", {
        timeZone: timezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date());
    } catch {
      // Unknown timezone -- fall back to the browser's local date.
    }
  }
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
}

export function formatTime(iso: string | null | undefined, timezone?: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: timezone || undefined,
  }).format(date);
}

export function formatDate(iso: string | null | undefined, timezone?: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: timezone || undefined,
  }).format(date);
}

export function formatDateTime(iso: string | null | undefined, timezone?: string): string {
  if (!iso) return "—";
  return `${formatDate(iso, timezone)}, ${formatTime(iso, timezone)}`;
}

export function formatDuration(seconds: number): string {
  if (!seconds || seconds < 0) return "—";
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes === 0) return `${remainder}s`;
  return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const deltaSeconds = Math.round((then - Date.now()) / 1000);
  const absolute = Math.abs(deltaSeconds);
  const units: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [3600, "minute"],
    [86400, "hour"],
    [604800, "day"],
  ];
  if (absolute < 60) return "just now";
  if (absolute < 3600) return `${Math.round(deltaSeconds / 60)} min`;
  if (absolute < 86400) return `${Math.round(deltaSeconds / 3600)} h`;
  if (absolute < 604800) return `${Math.round(deltaSeconds / 86400)} d`;
  void units;
  return formatDate(iso);
}

export const DOCTOR_STATUS_TONE: Record<DoctorStatus, "green" | "amber" | "red" | "slate" | "blue"> = {
  present: "green",
  running_late: "amber",
  unavailable: "red",
  on_leave: "red",
  finished_for_day: "slate",
  scheduled: "blue",
  unknown: "slate",
};

export const DOCTOR_STATUS_LABEL: Record<DoctorStatus, string> = {
  present: "Present",
  running_late: "Running late",
  unavailable: "Unavailable",
  on_leave: "On leave",
  finished_for_day: "Finished for day",
  scheduled: "Scheduled",
  unknown: "Unknown",
};

export const APPOINTMENT_STATUS_TONE: Record<
  AppointmentStatus,
  "green" | "amber" | "red" | "slate" | "blue" | "violet"
> = {
  booked: "blue",
  confirmed: "green",
  checked_in: "violet",
  completed: "slate",
  cancelled: "red",
  no_show: "red",
  reschedule_pending: "amber",
};

export const APPOINTMENT_STATUS_LABEL: Record<AppointmentStatus, string> = {
  booked: "Booked",
  confirmed: "Confirmed",
  checked_in: "Checked in",
  completed: "Completed",
  cancelled: "Cancelled",
  no_show: "No show",
  reschedule_pending: "Reschedule pending",
};

export const TASK_STATUS_TONE: Record<string, "green" | "amber" | "red" | "slate" | "blue"> = {
  open: "blue",
  in_progress: "amber",
  resolved: "green",
  declined: "slate",
  not_required: "slate",
};

export const PRIORITY_TONE: Record<string, "green" | "amber" | "red" | "slate" | "blue"> = {
  low: "slate",
  normal: "blue",
  high: "amber",
  urgent: "red",
};

export const OUTCOME_TONE: Record<string, "green" | "amber" | "red" | "slate"> = {
  resolved: "green",
  booked: "green",
  escalated: "amber",
  unresolved: "amber",
  abandoned: "slate",
  failed: "red",
  out_of_hours: "slate",
};

export function humanise(value: string): string {
  if (!value) return "";
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/**
 * Mirrors `Patient.prefers()` on the backend: a patient who has opted out of
 * a channel must never be messaged on it.
 */
export function patientPrefers(
  patient: { communication_preferences?: Record<string, boolean> } | null | undefined,
  channel: string,
): boolean {
  const preferences = patient?.communication_preferences ?? {};
  return !Boolean(preferences[`opt_out_${channel}`]);
}
