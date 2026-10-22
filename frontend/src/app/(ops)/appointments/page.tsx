"use client";

/**
 * The appointment list.
 *
 * Booking goes through the backend's booking service, which owns conflict
 * detection. This screen never decides for itself whether a slot is free --
 * it asks the API, and the API refuses a double booking.
 */
import { useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Modal,
  Select,
  Spinner,
  StatusBadge,
  Table,
  Textarea,
} from "@/components/ui";
import { formatDate, formatDateTime, formatTime } from "@/lib/format";
import type { Appointment, Doctor, Patient, Paginated, Slot } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

const STATUS_FILTERS = [
  { value: "", label: "All statuses" },
  { value: "booked", label: "Booked" },
  { value: "confirmed", label: "Confirmed" },
  { value: "checked_in", label: "Checked in" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "no_show", label: "No show" },
  { value: "reschedule_pending", label: "Reschedule pending" },
];

const OCCUPYING = ["booked", "confirmed", "checked_in", "reschedule_pending"];

function BookModal({
  isOpen,
  onClose,
  onBooked,
}: {
  isOpen: boolean;
  onClose: () => void;
  onBooked: () => void;
}) {
  const { api } = useAuth();
  const [doctorId, setDoctorId] = useState("");
  const [patientId, setPatientId] = useState("");
  const [patientPhone, setPatientPhone] = useState("");
  const [patientName, setPatientName] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [slotIso, setSlotIso] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const { data: doctors } = useApiData<{ doctors: Paginated<Doctor> }>(async (apiClient, signal) => {
    const doctors = await apiClient.get<Paginated<Doctor>>("/doctors/", { signal });
    return { doctors };
  }, isOpen ? "book-doctors" : "book-doctors-idle");

  const { data: patients } = useApiData<{ patients: Paginated<Patient> }>(async (apiClient, signal) => {
    const patients = await apiClient.get<Paginated<Patient>>("/patients/", { signal });
    return { patients };
  }, isOpen ? "book-patients" : "book-patients-idle");

  const { data: slots, loading: slotsLoading, reload: reloadSlots } = useApiData<{
    results: Slot[];
  }>(async (apiClient, signal) => {
    if (!date || !doctorId) return { results: [] };
    const payload = await apiClient.get<{ results: Slot[] }>("/availability/slots/", {
      params: { date, doctor: doctorId },
      signal,
    });
    return payload;
  }, `${date}:${doctorId}`);

  const selectedSlot = slots?.results.find((slot) => slot.start_at === slotIso) ?? null;

  async function book() {
    if (!doctorId || !patientId || !selectedSlot) {
      setError(new Error("Choose a doctor, a patient and a free slot."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post("/appointments/", {
        doctor: doctorId,
        patient: patientId,
        start_at: selectedSlot.start_at,
        notes,
        booking_source: "dashboard",
      });
      onBooked();
      onClose();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function findOrCreatePatient() {
    if (!patientPhone.trim()) {
      setError(new Error("Enter a phone number to look up the patient."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const found = await api.get<Paginated<Patient>>("/patients/", {
        params: { phone: patientPhone.trim() },
      });
      const existing = found.results[0];
      if (existing) {
        setPatientId(existing.id);
        setPatientName(existing.name);
        setError(null);
        return;
      }
      const created = await api.post<Patient>("/patients/", {
        name: patientName.trim(),
        phone: patientPhone.trim(),
        communication_preferences: {},
      });
      setPatientId(created.id);
      setPatientName(created.name);
      reloadSlots();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Book an appointment"
      action={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={book} disabled={busy}>
            {busy ? "Booking…" : "Book appointment"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {error ? <ErrorBanner error={error} /> : null}

        <Field label="Doctor">
          <Select value={doctorId} onChange={(event) => setDoctorId(event.target.value)}>
            <option value="">Select a doctor</option>
            {doctors?.doctors.results.map((doctor) => (
              <option key={doctor.id} value={doctor.id}>
                {doctor.name}
                {doctor.specialization ? ` — ${doctor.specialization}` : ""}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Patient" hint="Search by phone. A new record is created if none exists.">
          <div className="flex gap-2">
            <Input
              value={patientPhone}
              onChange={(event) => setPatientPhone(event.target.value)}
              placeholder="+91 98765 43210"
              inputMode="tel"
            />
            <Button variant="secondary" onClick={findOrCreatePatient} disabled={busy}>
              Find
            </Button>
          </div>
        </Field>

        {patientId ? (
          <div
            className="flex items-center gap-2 px-3 py-2 text-body-sm"
            style={{
              backgroundColor: "var(--color-success-light)",
              color: "var(--color-success)",
              borderRadius: "var(--radius-card)",
            }}
          >
            Selected: {patientName || "Unnamed patient"}
          </div>
        ) : null}

        <Field label="Date">
          <Input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        </Field>

        <Field label="Time" hint="Only slots the backend reports as free are listed.">
          {slotsLoading ? (
            <Spinner label="Checking availability…" />
          ) : !doctorId ? (
            <p className="text-body-sm" style={{ color: "var(--color-text-muted)" }}>
              Choose a doctor to see free slots.
            </p>
          ) : !slots || slots.results.length === 0 ? (
            <p className="text-body-sm" style={{ color: "var(--color-text-muted)" }}>
              No slots on this date.
            </p>
          ) : (
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
              {slots.results.map((slot) => {
                const available = slot.available;
                const selected = slotIso === slot.start_at;
                return (
                  <button
                    key={slot.start_at}
                    type="button"
                    disabled={!available}
                    onClick={() => setSlotIso(slot.start_at)}
                    aria-pressed={selected}
                    className="btn"
                    style={{
                      height: "auto",
                      minHeight: "2.5rem",
                      padding: "0.375rem 0.5rem",
                      fontSize: "var(--text-body-sm)",
                      backgroundColor: selected
                        ? "var(--color-brand)"
                        : "var(--color-surface-elevated)",
                      color: selected
                        ? "white"
                        : available
                          ? "var(--color-text-primary)"
                          : "var(--color-text-muted)",
                      borderColor: selected
                        ? "var(--color-brand)"
                        : "var(--color-border-subtle)",
                      cursor: available ? "pointer" : "not-allowed",
                      opacity: available ? 1 : 0.55,
                    }}
                    title={available ? slot.display_start : slot.reason}
                  >
                    {slot.display_start}
                  </button>
                );
              })}
            </div>
          )}
        </Field>

        <Field label="Notes" hint="Optional. Visible to clinic staff only.">
          <Textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Follow-up visit"
            rows={3}
          />
        </Field>
      </div>
    </Modal>
  );
}

function RescheduleModal({
  appointment,
  onClose,
  onDone,
}: {
  appointment: Appointment | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const { api } = useAuth();
  const [date, setDate] = useState("");
  const [slotIso, setSlotIso] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const { data: slots, loading } = useApiData<{ results: Slot[] }>(async (apiClient, signal) => {
    if (!appointment || !date) return { results: [] };
    const payload = await apiClient.get<{ results: Slot[] }>("/availability/slots/", {
      params: { date, doctor: appointment.doctor },
      signal,
    });
    return payload;
  }, `${appointment?.id ?? ""}:${date}`);

  async function reschedule() {
    if (!appointment || !slotIso) {
      setError(new Error("Pick a new time first."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post(`/appointments/${appointment.id}/reschedule/`, { start_at: slotIso });
      onDone();
      onClose();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (!appointment) return null;

  return (
    <Modal
      isOpen={Boolean(appointment)}
      onClose={onClose}
      title={`Reschedule ${appointment.reference}`}
      action={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Keep current time
          </Button>
          <Button variant="primary" onClick={reschedule} disabled={busy}>
            {busy ? "Moving…" : "Move appointment"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {error ? <ErrorBanner error={error} /> : null}

        <div className="text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
          Currently {formatDateTime(appointment.start_at)} with {appointment.doctor_name}.
        </div>

        <Field label="New date">
          <Input
            type="date"
            value={date}
            onChange={(event) => {
              setDate(event.target.value);
              setSlotIso("");
            }}
          />
        </Field>

        <Field label="New time">
          {loading ? (
            <Spinner label="Checking availability…" />
          ) : !date ? (
            <p className="text-body-sm" style={{ color: "var(--color-text-muted)" }}>
              Choose a date to see free slots.
            </p>
          ) : !slots || slots.results.length === 0 ? (
            <p className="text-body-sm" style={{ color: "var(--color-text-muted)" }}>
              No slots on this date.
            </p>
          ) : (
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
              {slots.results.map((slot) => {
                const selected = slotIso === slot.start_at;
                return (
                  <button
                    key={slot.start_at}
                    type="button"
                    disabled={!slot.available}
                    onClick={() => setSlotIso(slot.start_at)}
                    aria-pressed={selected}
                    className="btn"
                    style={{
                      height: "auto",
                      minHeight: "2.5rem",
                      padding: "0.375rem 0.5rem",
                      fontSize: "var(--text-body-sm)",
                      backgroundColor: selected
                        ? "var(--color-brand)"
                        : "var(--color-surface-elevated)",
                      color: selected ? "white" : "var(--color-text-primary)",
                      borderColor: selected ? "var(--color-brand)" : "var(--color-border-subtle)",
                      opacity: slot.available ? 1 : 0.55,
                      cursor: slot.available ? "pointer" : "not-allowed",
                    }}
                    title={slot.available ? slot.display_start : slot.reason}
                  >
                    {slot.display_start}
                  </button>
                );
              })}
            </div>
          )}
        </Field>
      </div>
    </Modal>
  );
}

function CancelModal({
  appointment,
  onClose,
  onDone,
}: {
  appointment: Appointment | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const { api } = useAuth();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function cancel() {
    if (!appointment) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/appointments/${appointment.id}/cancel/`, { reason });
      onDone();
      onClose();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (!appointment) return null;

  return (
    <Modal
      isOpen={Boolean(appointment)}
      onClose={onClose}
      title={`Cancel ${appointment.reference}`}
      action={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Keep appointment
          </Button>
          <Button variant="danger" onClick={cancel} disabled={busy}>
            {busy ? "Cancelling…" : "Cancel appointment"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {error ? <ErrorBanner error={error} /> : null}
        <p className="text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
          {appointment.patient_name || "This patient"} · {formatDateTime(appointment.start_at)} with{" "}
          {appointment.doctor_name}.
        </p>
        <Field label="Reason" hint="Recorded on the appointment for the audit trail.">
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Patient called to cancel"
            rows={3}
            maxLength={255}
          />
        </Field>
      </div>
    </Modal>
  );
}

export default function AppointmentsPage() {
  const { activeClinic, activeClinicId } = useAuth();
  const timezone = activeClinic?.timezone;

  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [booking, setBooking] = useState(false);
  const [rescheduling, setRescheduling] = useState<Appointment | null>(null);
  const [cancelling, setCancelling] = useState<Appointment | null>(null);

  const { data, error, loading, reload } = useApiData<{
    appointments: Paginated<Appointment>;
  }>(async (api, signal) => {
    const appointments = await api.get<Paginated<Appointment>>("/appointments/", {
      params: status ? { status } : undefined,
      signal,
    });
    return { appointments };
  }, `${activeClinicId ?? ""}:${status}`);

  const rows = useMemo(() => {
    const list = data?.appointments.results ?? [];
    if (!search.trim()) return list;
    const needle = search.trim().toLowerCase();
    return list.filter(
      (appointment) =>
        appointment.patient_name?.toLowerCase().includes(needle) ||
        appointment.reference?.toLowerCase().includes(needle) ||
        appointment.doctor_name?.toLowerCase().includes(needle) ||
        appointment.patient_phone?.includes(needle),
    );
  }, [data, search]);

  const grouped = useMemo(() => {
    const groups = new Map<string, Appointment[]>();
    for (const appointment of rows) {
      const key = formatDate(appointment.start_at, timezone);
      const bucket = groups.get(key);
      if (bucket) bucket.push(appointment);
      else groups.set(key, [appointment]);
    }
    return Array.from(groups.entries());
  }, [rows, timezone]);

  if (loading) return <Spinner label="Loading appointments…" size="lg" />;
  if (error) return <ErrorBanner error={error} />;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Appointments</h1>
          <p className="page-subtitle">
            {data?.appointments.count ?? 0} appointment
            {data?.appointments.count === 1 ? "" : "s"} in this view.
          </p>
        </div>
        <Button variant="primary" onClick={() => setBooking(true)}>
          Book appointment
        </Button>
      </header>

      <Card
        title="Schedule"
        subtitle="Grouped by day. Times are shown in the clinic's timezone."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search patient, reference or doctor"
              aria-label="Search appointments"
              style={{ width: "16rem" }}
            />
            <Select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              aria-label="Filter by status"
              style={{ width: "12rem" }}
            >
              {STATUS_FILTERS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </div>
        }
      >
        {grouped.length === 0 ? (
          <EmptyState
            title="No appointments match this view"
            hint="Change the filter, or book the first appointment for the day."
            action={
              <Button variant="primary" onClick={() => setBooking(true)}>
                Book appointment
              </Button>
            }
          />
        ) : (
          <div className="space-y-6">
            {grouped.map(([day, appointments]) => (
              <div key={day}>
                <h3
                  className="mb-2 text-body-sm font-medium"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  {day}
                </h3>
                <div className="table-wrapper">
                  <table className="table table-dense">
                    <thead>
                      <tr>
                        <th style={{ width: "6rem" }}>Time</th>
                        <th>Patient</th>
                        <th>Doctor</th>
                        <th>Status</th>
                        <th style={{ width: "12rem" }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {appointments.map((appointment) => {
                        const active = OCCUPYING.includes(appointment.status);
                        return (
                          <tr key={appointment.id}>
                            <td style={{ color: "var(--color-text-secondary)" }}>
                              {formatTime(appointment.start_at, timezone)}
                            </td>
                            <td>
                              <p className="font-medium" style={{ color: "var(--color-text-primary)" }}>
                                {appointment.patient_name || "Unnamed patient"}
                              </p>
                              <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
                                {appointment.reference} · {appointment.patient_phone}
                              </p>
                            </td>
                            <td style={{ color: "var(--color-text-secondary)" }}>
                              {appointment.doctor_name}
                            </td>
                            <td>
                              <StatusBadge status={appointment.status} />
                            </td>
                            <td>
                              {active ? (
                                <div className="flex gap-1">
                                  <Button
                                    variant="ghost"
                                    onClick={() => setRescheduling(appointment)}
                                    aria-label={`Reschedule ${appointment.reference}`}
                                  >
                                    Reschedule
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    onClick={() => setCancelling(appointment)}
                                    aria-label={`Cancel ${appointment.reference}`}
                                  >
                                    Cancel
                                  </Button>
                                </div>
                              ) : (
                                <Badge tone="neutral">Closed</Badge>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <BookModal isOpen={booking} onClose={() => setBooking(false)} onBooked={reload} />
      <RescheduleModal
        appointment={rescheduling}
        onClose={() => setRescheduling(null)}
        onDone={reload}
      />
      <CancelModal appointment={cancelling} onClose={() => setCancelling(null)} onDone={reload} />
    </div>
  );
}