"use client";

/**
 * The doctor board.
 *
 * Presence is an explicit assertion: choosing a status here records a status
 * *event* with a source and a timestamp. It never edits history -- the event
 * log is append-only, so the clinic can always see who said what and when.
 * Admins can also add and edit doctors; a doctor added here immediately appears
 * in appointments and on the public booking page.
 */
import { useCallback, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Modal,
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

interface DoctorFormState {
  name: string;
  specialization: string;
  phone: string;
  languages: string;
  sort_order: string;
  is_active: boolean;
}

const EMPTY_FORM: DoctorFormState = {
  name: "",
  specialization: "",
  phone: "",
  languages: "",
  sort_order: "0",
  is_active: true,
};

interface DoctorRowProps {
  doctor: Doctor;
  availability: DoctorAvailability | null;
  timezone: string | undefined;
  canUpdate: boolean;
  isAdmin: boolean;
  editing: boolean;
  status: DoctorStatus;
  notes: string;
  busy: boolean;
  onStart: () => void;
  onCancel: () => void;
  onStatusChange: (status: DoctorStatus) => void;
  onNotesChange: (notes: string) => void;
  onSubmit: () => void;
  onEdit: () => void;
}

function DoctorRow({
  doctor,
  availability,
  timezone,
  canUpdate,
  isAdmin,
  editing,
  status,
  notes,
  busy,
  onStart,
  onCancel,
  onStatusChange,
  onNotesChange,
  onSubmit,
  onEdit,
}: DoctorRowProps) {
  if (editing) {
    return (
      <tr>
        <td className="px-4 py-3" colSpan={6}>
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
      <td className="px-4 py-3">
        {isAdmin ? (
          <Button variant="ghost" onClick={onEdit} aria-label={`Edit ${doctor.name}`}>
            Edit
          </Button>
        ) : null}
      </td>
    </tr>
  );
}

function DoctorEditor({
  doctor,
  onClose,
  onSaved,
}: {
  doctor: Doctor | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { api } = useAuth();
  const [form, setForm] = useState<DoctorFormState>(() =>
    doctor
      ? {
          name: doctor.name,
          specialization: doctor.specialization,
          phone: doctor.phone,
          languages: (doctor.languages ?? []).join(", "),
          sort_order: String(doctor.sort_order ?? 0),
          is_active: doctor.is_active,
        }
      : EMPTY_FORM,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function update(field: keyof DoctorFormState, value: string | boolean) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function save() {
    if (!form.name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const payload = {
        name: form.name.trim(),
        specialization: form.specialization.trim(),
        phone: form.phone.trim(),
        languages: form.languages
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        sort_order: Number(form.sort_order) || 0,
        is_active: form.is_active,
      };
      if (doctor) {
        await api.patch(`/doctors/${doctor.id}/`, payload);
      } else {
        await api.post("/doctors/", payload);
      }
      onSaved();
      onClose();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={doctor ? `Edit ${doctor.name}` : "Add a doctor"}
      action={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} disabled={busy || !form.name.trim()}>
            {busy ? "Saving…" : "Save doctor"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? <ErrorBanner error={error} /> : null}
        <Field label="Full name">
          <Input value={form.name} onChange={(e) => update("name", e.target.value)} placeholder="Dr. Ada Lovelace" />
        </Field>
        <Field label="Specialisation">
          <Input
            value={form.specialization}
            onChange={(e) => update("specialization", e.target.value)}
            placeholder="General practice"
          />
        </Field>
        <Field label="Phone">
          <Input value={form.phone} onChange={(e) => update("phone", e.target.value)} placeholder="+91 98765 43210" />
        </Field>
        <Field label="Languages" hint="Comma-separated, e.g. English, Hindi">
          <Input
            value={form.languages}
            onChange={(e) => update("languages", e.target.value)}
            placeholder="English, Hindi"
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Sort order">
            <Input
              type="number"
              value={form.sort_order}
              onChange={(e) => update("sort_order", e.target.value)}
            />
          </Field>
          <Field label="Availability">
            <Select
              value={form.is_active ? "active" : "inactive"}
              onChange={(e) => update("is_active", e.target.value === "active")}
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </Select>
          </Field>
        </div>
        {!doctor ? (
          <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
            The doctor will appear on the roster, in appointment booking, and on the public
            booking page as soon as this is saved.
          </p>
        ) : null}
      </div>
    </Modal>
  );
}

function StatusHistory({ timezone }: { timezone: string | undefined }) {
  const { activeClinicId } = useAuth();
  const [doctorId, setDoctorId] = useState<string>("");

  const { data: roster } = useApiData<{ doctors: Paginated<Doctor> }>(async (api, signal) => {
    const doctors = await api.get<Paginated<Doctor>>("/doctors/", { signal });
    return { doctors };
  }, "status-history-roster");

  const { data, error, loading } = useApiData<{
    current: DoctorStatusCurrent | null;
    events: DoctorStatusEvent[];
  }>(async (api, signal) => {
    if (!doctorId) return { current: null, events: [] };
    return api.get<{ current: DoctorStatusCurrent | null; events: DoctorStatusEvent[] }>(
      `/doctors/${doctorId}/status-history/`,
      { signal },
    );
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
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingDoctor, setEditingDoctor] = useState<Doctor | null>(null);

  const { data, error, loading, refreshing, reload } = useApiData<{
    doctors: Paginated<Doctor>;
    availability: Record<string, DoctorAvailability>;
  }>(async (apiClient, signal) => {
    const doctors = await apiClient.get<Paginated<Doctor>>("/doctors/", { signal });
    // Fetch availability in parallel but tolerate a provider error per doctor.
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
  }, "roster");

  const canUpdate = role === "clinic_admin" || role === "doctor";
  const isAdmin = role === "clinic_admin";

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
        {isAdmin ? (
          <Button
            variant="primary"
            onClick={() => {
              setEditingDoctor(null);
              setEditorOpen(true);
            }}
          >
            Add doctor
          </Button>
        ) : null}
      </header>

      {actionError ? (
        <div style={{ marginBottom: "var(--space-section)" }}>
          <ErrorBanner error={actionError} />
        </div>
      ) : null}
      {refreshing ? (
        <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
          Refreshing…
        </p>
      ) : null}

      <Card title="Roster" subtitle={`${data?.doctors.count ?? 0} active doctors`}>
        {loading && !data ? (
          <Spinner label="Loading the roster…" />
        ) : error && !data ? (
          <ErrorBanner error={error} />
        ) : (
          <Table
            headers={["Doctor", "Languages", "Status", "Last confirmed", "Actions", ""]}
            empty="No doctors on the roster yet. Add one to make them bookable."
          >
            {data?.doctors.results.map((doctor) => (
              <DoctorRow
                key={doctor.id}
                doctor={doctor}
                availability={data?.availability[doctor.id] ?? null}
                timezone={timezone}
                canUpdate={canUpdate}
                isAdmin={isAdmin}
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
                onEdit={() => {
                  setEditingDoctor(doctor);
                  setEditorOpen(true);
                }}
              />
            ))}
          </Table>
        )}
      </Card>

      {activeClinicId ? (
        <div style={{ marginTop: "var(--space-section)" }}>
          <StatusHistory timezone={timezone} />
        </div>
      ) : null}

      {editorOpen ? (
        <DoctorEditor
          doctor={editingDoctor}
          onClose={() => setEditorOpen(false)}
          onSaved={reload}
        />
      ) : null}
    </div>
  );
}
