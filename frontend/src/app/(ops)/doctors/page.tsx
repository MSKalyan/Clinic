"use client";

/**
 * The doctor board.
 *
 * Presence is an explicit assertion: choosing a status here records a
 * status *event* with a source and a timestamp. It never edits history --
 * the event log is append-only, so the clinic can always see who said what
 * and when.
 */
import { useCallback, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Select,
  Spinner,
  Table,
  Textarea,
  StatusBadge,
} from "@/components/ui";
import { formatDateTime, formatTime, humanise } from "@/lib/format";
import type {
  Doctor,
  DoctorAvailability,
  DoctorStatus,
  DoctorStatusCurrent,
  DoctorStatusEvent,
  Paginated,
} from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

const STATUSES: DoctorStatus[] = [
  "present",
  "running_late",
  "unavailable",
  "on_leave",
  "finished_for_day",
];

const STATUS_LABELS: Record<string, string> = {
  present: "Present",
  running_late: "Running late",
  unavailable: "Unavailable",
  on_leave: "On leave",
  finished_for_day: "Finished for day",
  scheduled: "Scheduled",
  unknown: "Unknown",
};

interface DoctorRowProps {
  doctor: Doctor;
  availability: DoctorAvailability | null;
  timezone: string | undefined;
  canUpdate: boolean;
  editing: boolean;
  status: DoctorStatus;
  notes: string;
  busy: boolean;
  onStart: () => void;
  onCancel: () => void;
  onStatusChange: (status: DoctorStatus) => void;
  onNotesChange: (notes: string) => void;
  onSubmit: () => void;
}

function DoctorRow({
  doctor,
  availability,
  timezone,
  canUpdate,
  editing,
  status,
  notes,
  busy,
  onStart,
  onCancel,
  onStatusChange,
  onNotesChange,
  onSubmit,
}: DoctorRowProps) {
  if (editing) {
    return (
      <tr>
        <td className="px-4 py-3" colSpan={5}>
          <div
            className="flex flex-wrap items-end gap-3 p-4"
            style={{
              backgroundColor: "var(--color-surface-subtle)",
              borderRadius: "var(--radius-card)",
            }}
          >
            <div className="flex-1 min-w-[180px]">
              <p className="font-medium" style={{ color: "var(--color-text-primary)" }}>
                {doctor.name}
              </p>
              <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
                Recording a status event for {doctor.name}
              </p>
            </div>
            <div className="min-w-[180px]">
              <Field label="Status">
                <Select
                  value={status}
                  onChange={(event) => onStatusChange(event.target.value as DoctorStatus)}
                  disabled={busy}
                >
                  {STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {STATUS_LABELS[value]}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <div className="min-w-[220px] flex-1">
              <Field label="Notes" hint="Optional. Recorded on the event, never edited.">
                <Textarea
                  value={notes}
                  onChange={(event) => onNotesChange(event.target.value)}
                  placeholder="Arrived ten minutes late"
                  rows={2}
                  disabled={busy}
                  maxLength={500}
                />
              </Field>
            </div>
            <div className="flex gap-2">
              <Button variant="primary" onClick={onSubmit} disabled={busy}>
                {busy ? "Recording…" : "Record status"}
              </Button>
              <Button variant="ghost" onClick={onCancel} disabled={busy}>
                Cancel
              </Button>
            </div>
          </div>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td className="px-4 py-3">
        <p className="font-medium" style={{ color: "var(--color-text-primary)" }}>
          {doctor.name}
        </p>
        <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
          {doctor.specialization || "No specialisation recorded"}
        </p>
      </td>
      <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
        {doctor.languages?.length ? doctor.languages.join(", ") : "—"}
      </td>
      <td className="px-4 py-3">
        <StatusBadge
          status={availability?.status ?? "unknown"}
          isStale={availability?.is_stale}
        />
      </td>
      <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
        {availability?.last_confirmed_at
          ? formatTime(availability.last_confirmed_at, timezone)
          : "—"}
      </td>
      <td className="px-4 py-3">
        {canUpdate ? (
          <Button variant="ghost" onClick={onStart} aria-label={`Set status for ${doctor.name}`}>
            Set status
          </Button>
        ) : (
          <span className="text-caption" style={{ color: "var(--color-text-muted)" }}>
            Read only
          </span>
        )}
      </td>
    </tr>
  );
}

function StatusHistory({ timezone }: { timezone: string | undefined }) {
  const { activeClinicId } = useAuth();
  const [doctorId, setDoctorId] = useState<string>("");

  const { data: roster } = useApiData<{ doctors: Paginated<Doctor> }>(async (api, signal) => {
    const doctors = await api.get<Paginated<Doctor>>("/doctors/", { signal });
    return { doctors };
  }, activeClinicId ?? "roster");

  const { data, error, loading } = useApiData<{
    current: DoctorStatusCurrent | null;
    events: DoctorStatusEvent[];
  }>(async (api, signal) => {
    if (!doctorId) return { current: null, events: [] };
    const payload = await api.get<{
      current: DoctorStatusCurrent | null;
      events: DoctorStatusEvent[];
    }>(`/doctors/${doctorId}/status-history/`, { signal });
    return payload;
  }, doctorId);

  return (
    <Card
      title="Status history"
      subtitle="The append-only event log. Every change keeps its author and timestamp."
      className="mt-6"
    >
      <div className="mb-5 max-w-xs">
        <Field label="Doctor">
          <Select
            value={doctorId}
            onChange={(event) => setDoctorId(event.target.value)}
            aria-label="Select a doctor to view status history"
          >
            <option value="">Select a doctor</option>
            {roster?.doctors.results.map((doctor) => (
              <option key={doctor.id} value={doctor.id}>
                {doctor.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {!doctorId ? (
        <EmptyState
          title="Choose a doctor to see their status log"
          hint="Each status change is kept forever. Nothing is overwritten."
        />
      ) : loading ? (
        <Spinner label="Loading history…" />
      ) : error ? (
        <ErrorBanner error={error} />
      ) : !data || data.events.length === 0 ? (
        <EmptyState
          title="No status events yet"
          hint="Recording a status above will create the first event."
        />
      ) : (
        <Table headers={["Recorded", "Status", "Source", "Recorded by", "Notes"]} empty="No events.">
          {data.events.map((event) => (
            <tr key={event.id}>
              <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                {formatDateTime(event.created_at, timezone)}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={event.status} />
              </td>
              <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                {humanise(event.source)}
              </td>
              <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                {event.updated_by_identifier || "—"}
              </td>
              <td className="px-4 py-3" style={{ color: "var(--color-text-muted)" }}>
                {event.notes || "—"}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export default function DoctorsPage() {
  const { api, activeClinic, activeClinicId } = useAuth();
  const timezone = activeClinic?.timezone;
  const role = activeClinic?.role;

  const [editing, setEditing] = useState<string | null>(null);
  const [status, setStatus] = useState<DoctorStatus>("present");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);

  const { data, error, loading, reload } = useApiData<{
    doctors: Paginated<Doctor>;
    availability: Record<string, DoctorAvailability>;
  }>(async (apiClient, signal) => {
    const doctors = await apiClient.get<Paginated<Doctor>>("/doctors/", { signal });
    const entries = await Promise.all(
      doctors.results.map((doctor) =>
        apiClient
          .get<DoctorAvailability>(`/doctors/${doctor.id}/availability/`, { signal })
          .then((availability) => [doctor.id, availability] as const)
          .catch(() => [doctor.id, null] as const),
      ),
    );
    return {
      doctors,
      availability: Object.fromEntries(entries) as Record<string, DoctorAvailability>,
    };
  }, activeClinicId ?? "roster");

  const canUpdate = role === "clinic_admin" || role === "doctor";

  const recordStatus = useCallback(
    async (doctorId: string) => {
      setBusy(true);
      setActionError(null);
      try {
        await api.post(`/doctors/${doctorId}/availability-events/`, {
          status,
          notes,
          source: "dashboard",
        });
        setEditing(null);
        setNotes("");
        setStatus("present");
        reload();
      } catch (cause) {
        setActionError(cause);
      } finally {
        setBusy(false);
      }
    },
    [api, notes, reload, status],
  );

  if (loading) return <Spinner label="Loading the roster…" size="lg" />;
  if (error) return <ErrorBanner error={error} />;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Doctors</h1>
          <p className="page-subtitle">
            Status is recorded explicitly. A rota entry is a schedule, not a confirmation that the
            doctor has arrived.
          </p>
        </div>
      </header>

      {actionError ? (
        <div style={{ marginBottom: "var(--space-section)" }}>
          <ErrorBanner error={actionError} />
        </div>
      ) : null}

      <Card title="Roster" subtitle={`${data?.doctors.count ?? 0} active doctors`}>
        <Table
          headers={["Doctor", "Languages", "Status", "Last confirmed", "Actions"]}
          empty="No doctors on the roster yet."
        >
          {data?.doctors.results.map((doctor) => (
            <DoctorRow
              key={doctor.id}
              doctor={doctor}
              availability={data?.availability[doctor.id] ?? null}
              timezone={timezone}
              canUpdate={canUpdate}
              editing={editing === doctor.id}
              status={status}
              notes={notes}
              busy={busy}
              onStart={() => {
                setEditing(doctor.id);
                setStatus("present");
                setNotes("");
              }}
              onCancel={() => setEditing(null)}
              onStatusChange={setStatus}
              onNotesChange={setNotes}
              onSubmit={() => recordStatus(doctor.id)}
            />
          ))}
        </Table>
      </Card>

      {activeClinicId ? (
        <div style={{ marginTop: "var(--space-section)" }}>
          <StatusHistory timezone={timezone} />
        </div>
      ) : null}
    </div>
  );
}