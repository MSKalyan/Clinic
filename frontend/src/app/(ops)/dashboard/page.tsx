"use client";

import { useCallback } from "react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import {
  Badge,
  Button,
  Card,
  ErrorBanner,
  Spinner,
  StatCard,
  Table,
  StatusBadge,
} from "@/components/ui";
import {
  formatTime,
  humanise,
} from "@/lib/format";
import type { Appointment, DashboardSummary, FollowUpTask, Paginated } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";
import { useClinicSocket } from "@/lib/use-clinic-socket";

export default function DashboardPage() {
  const { activeClinic } = useAuth();
  const timezone = activeClinic?.timezone;

  const { data, error, loading, refreshing, reload } = useApiData<{
    summary: DashboardSummary;
    appointments: Paginated<Appointment>;
    tasks: Paginated<FollowUpTask>;
  }>(async (api, signal) => {
    const [summary, appointments, tasks] = await Promise.all([
      api.get<DashboardSummary>("/dashboard/summary/"),
      api.get<Paginated<Appointment>>("/appointments/", {
        params: { status: "booked,confirmed,checked_in,reschedule_pending" },
        signal,
      }),
      api.get<Paginated<FollowUpTask>>("/follow-ups/", {
        params: { status: "open,in_progress" },
        signal,
      }),
    ]);
    return { summary, appointments, tasks };
  });

  // Debounce live reloads so a burst of events (e.g. several messages) causes
  // one re-fetch, not a stampede.
  const reloadTimer = useCallback(() => {
    // The hook's reload is stable; a small timeout coalesces bursts.
    window.clearTimeout((window as unknown as { _dashReload?: number })._dashReload);
    (window as unknown as { _dashReload?: number })._dashReload = window.setTimeout(
      reload,
      250,
    );
  }, [reload]);

  const onEvent = useCallback(
    (event: { event: string }) => {
      if (
        event.event === "dashboard.changed" ||
        event.event === "conversation.message" ||
        event.event === "conversation.new"
      ) {
        reloadTimer();
      }
    },
    [reloadTimer],
  );

  const { connected } = useClinicSocket(onEvent);

  if (loading && !data) return <Spinner label="Loading today…" size="lg" />;
  if (error && !data) return <ErrorBanner error={error} />;
  if (!data) return null;

  const { summary, appointments, tasks } = data;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Today</h1>
          <p className="page-subtitle">
            {summary.clinic.name} · {summary.clinic.timezone} · generated{" "}
            {formatTime(summary.generated_at, timezone)}
            <span className="ml-2 inline-flex items-center gap-1 text-caption">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{
                  backgroundColor: connected ? "var(--color-success)" : "var(--color-text-muted)",
                }}
                aria-hidden
              />
              {connected ? "Live" : "Connecting…"}
              {refreshing ? " · updating" : ""}
            </span>
          </p>
        </div>
        <Button variant="secondary" onClick={reload} size="sm">
          Refresh
        </Button>
      </header>

      <div className="grid-4" style={{ marginBottom: "var(--space-section)" }}>
        <StatCard
          label="Appointments today"
          value={summary.appointments.today_total}
          hint={`${summary.appointments.upcoming_7_days} in the next 7 days`}
        />
        <StatCard
          label="Open follow-ups"
          value={summary.tasks.open + summary.tasks.in_progress}
          hint={`${summary.tasks.in_progress} in progress`}
          tone={summary.tasks.overdue > 0 ? "warning" : "neutral"}
        />
        <StatCard
          label="Overdue tasks"
          value={summary.tasks.overdue}
          hint="Past their due time"
          tone={summary.tasks.overdue > 0 ? "danger" : "success"}
        />
        <StatCard
          label="Unresolved calls"
          value={summary.calls.unresolved_7_days}
          hint={`${summary.calls.total_7_days} calls in 7 days`}
          tone={summary.calls.unresolved_7_days > 0 ? "warning" : "success"}
        />
      </div>

      <div className="grid-4" style={{ marginBottom: "var(--space-section)" }}>
        <StatCard
          label="Doctors present"
          value={`${summary.doctors.status.filter((d) => d.status === "present").length}/${summary.doctors.total}`}
          hint={summary.doctors.stale_count > 0 ? `${summary.doctors.stale_count} stale` : "All fresh"}
          tone={summary.doctors.stale_count > 0 ? "warning" : "success"}
        />
        <StatCard
          label="Open conversations"
          value={summary.conversations.open}
          hint={`${summary.conversations.escalated} escalated`}
        />
        <StatCard
          label="Reminders pending"
          value={summary.reminders.pending}
          hint={`${summary.reminders.failed} failed`}
          tone={summary.reminders.failed > 0 ? "danger" : "neutral"}
        />
        <StatCard
          label="Cancelled today"
          value={summary.appointments.cancelled_today}
          hint={`${summary.appointments.no_show_today} no-shows`}
          tone={summary.appointments.cancelled_today > 0 ? "warning" : "neutral"}
        />
      </div>

      <div className="grid-2" style={{ marginBottom: "var(--space-section)" }}>
        <Card
          title="Doctor status"
          subtitle="Presence is an explicit confirmation, never inferred from the rota."
          action={
            <Link href="/doctors" className="text-caption font-medium" style={{ color: "var(--color-brand)", textDecoration: "none" }}>
              Manage
            </Link>
          }
        >
          <Table
            headers={["Doctor", "Specialisation", "Status", "Last confirmed", "Arrival"]}
            empty="No doctors on the roster."
          >
            {summary.doctors.status.map((doctor) => (
              <tr key={doctor.doctor_id}>
                <td className="px-4 py-3">
                  <p className="font-medium" style={{ color: "var(--color-text-primary)" }}>{doctor.doctor_name}</p>
                </td>
                <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                  {doctor.specialization || "—"}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={doctor.status} isStale={doctor.is_stale} />
                </td>
                <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                  {doctor.last_confirmed_at ? formatTime(doctor.last_confirmed_at, timezone) : "—"}
                </td>
                <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                  {doctor.expected_arrival_at
                    ? formatTime(doctor.expected_arrival_at, timezone)
                    : "—"}
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card
          title="Upcoming appointments"
          subtitle="Booked, confirmed and checked-in."
          action={
            <Link
              href="/appointments"
              className="text-caption font-medium"
              style={{ color: "var(--color-brand)", textDecoration: "none" }}
            >
              All appointments
            </Link>
          }
        >
          <Table
            headers={["Time", "Patient", "Doctor", "Status"]}
            empty="Nothing booked ahead."
          >
            {appointments.results.slice(0, 8).map((appointment) => (
              <tr key={appointment.id}>
                <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                  {formatTime(appointment.start_at, timezone)}
                </td>
                <td className="px-4 py-3">
                  <p className="font-medium" style={{ color: "var(--color-text-primary)" }}>{appointment.patient_name || "—"}</p>
                  <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>{appointment.reference}</p>
                </td>
                <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>{appointment.doctor_name}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={appointment.status} />
                </td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>

      <Card
        title="Follow-up queue"
        subtitle="Work the assistant could not finish on its own."
        action={
          <Link href="/follow-ups" className="text-caption font-medium" style={{ color: "var(--color-brand)", textDecoration: "none" }}>
            Open queue
          </Link>
        }
      >
        <Table headers={["Task", "Patient", "Priority", "Due", "Status"]} empty="Queue is clear.">
          {tasks.results.slice(0, 8).map((task) => (
            <tr key={task.id}>
              <td className="px-4 py-3 font-medium" style={{ color: "var(--color-text-primary)" }}>{humanise(task.task_type)}</td>
              <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>{task.patient_name || "—"}</td>
              <td className="px-4 py-3">
                <StatusBadge status={task.priority} />
              </td>
              <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                {task.due_at ? formatTime(task.due_at, timezone) : "—"}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={task.status} />
              </td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}