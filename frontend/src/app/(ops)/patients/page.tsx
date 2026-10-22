"use client";

/**
 * The patient register.
 *
 * A patient's communication preferences are the switch that decides whether
 * the assistant is allowed to message them at all. They are shown on the
 * record, not buried in a settings page, because getting this wrong means
 * contacting someone who asked not to be contacted.
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
  Table,
  Textarea,
} from "@/components/ui";
import { formatDateTime, patientPrefers } from "@/lib/format";
import type { Paginated, Patient, PatientConsent } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

const CHANNELS = ["sms", "whatsapp", "voice"] as const;

function PatientModal({
  isOpen,
  onClose,
  onSaved,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { api } = useAuth();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [language, setLanguage] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function save() {
    if (!phone.trim()) {
      setError(new Error("A phone number is required. It identifies the patient inside the clinic."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post("/patients/", {
        name: name.trim(),
        phone: phone.trim(),
        preferred_language: language.trim(),
        notes,
        communication_preferences: {},
      });
      onSaved();
      onClose();
      setName("");
      setPhone("");
      setLanguage("");
      setNotes("");
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
      title="Add a patient"
      action={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Add patient"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {error ? <ErrorBanner error={error} /> : null}
        <Field label="Name" hint="Leave blank if the patient has not given their name.">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Ravi Patel"
            autoFocus
          />
        </Field>
        <Field label="Phone" hint="Unique inside the clinic. Used to match incoming calls and messages.">
          <Input
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder="+91 98765 43210"
            inputMode="tel"
          />
        </Field>
        <Field label="Preferred language" hint="Used to greet the patient on the channels they speak.">
          <Input
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
            placeholder="Hindi"
          />
        </Field>
        <Field label="Notes" hint="Only clinic staff can see this.">
          <Textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} />
        </Field>
      </div>
    </Modal>
  );
}

function PatientDetail({
  patient,
  onClose,
}: {
  patient: Patient | null;
  onClose: () => void;
}) {
  const { api } = useAuth();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [consents, setConsents] = useState<PatientConsent[]>([]);

  const { data, loading, reload } = useApiData<{ consents: PatientConsent[] }>(
    async (apiClient, signal) => {
      if (!patient) return { consents: [] };
      const payload = await apiClient.get<PatientConsent[]>(`/patients/${patient.id}/consents/`, {
        signal,
      });
      return { consents: payload ?? [] };
    },
    patient?.id ?? "none",
  );

  const list = data?.consents ?? consents;

  async function toggleOptOut(channel: string) {
    if (!patient) return;
    setBusy(channel);
    setError(null);
    const optOut = !patientPrefers(patient, channel);
    try {
      await api.post(`/patients/${patient.id}/communication-preferences/`, {
        channel,
        opt_out: optOut,
      });
      reload();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  }

  if (!patient) return null;

  return (
    <Modal
      isOpen={Boolean(patient)}
      onClose={onClose}
      title={patient.name || "Patient"}
      action={<Button variant="ghost" onClick={onClose}>Close</Button>}
    >
      <div className="space-y-6">
        {error ? <ErrorBanner error={error} /> : null}

        <div>
          <p className="text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
            {patient.phone}
            {patient.preferred_language ? ` · ${patient.preferred_language}` : ""}
          </p>
          {patient.notes ? (
            <p className="mt-2 text-body-sm" style={{ color: "var(--color-text-muted)" }}>
              {patient.notes}
            </p>
          ) : null}
        </div>

        <div>
          <h3 className="mb-1 text-body font-medium" style={{ color: "var(--color-text-primary)" }}>
            Communication preferences
          </h3>
          <p className="mb-3 text-body-sm" style={{ color: "var(--color-text-muted)" }}>
            A patient who opts out of a channel is never messaged on it by the assistant.
          </p>
          <div className="space-y-2">
            {CHANNELS.map((channel) => {
              const optedOut = !patientPrefers(patient, channel);
              return (
                <div
                  key={channel}
                  className="flex items-center justify-between px-3 py-2"
                  style={{
                    border: "1px solid var(--color-border-subtle)",
                    borderRadius: "var(--radius-card)",
                  }}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-body-sm capitalize" style={{ color: "var(--color-text-primary)" }}>
                      {channel}
                    </span>
                    {optedOut ? (
                      <Badge tone="danger">Opted out</Badge>
                    ) : (
                      <Badge tone="success">Allowed</Badge>
                    )}
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() => toggleOptOut(channel)}
                    disabled={busy === channel}
                  >
                    {busy === channel
                      ? "Saving…"
                      : optedOut
                        ? "Allow messages"
                        : "Opt out"}
                  </Button>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <h3 className="mb-3 text-body font-medium" style={{ color: "var(--color-text-primary)" }}>
            Consents
          </h3>
          {loading ? (
            <Spinner label="Loading consents…" />
          ) : list.length === 0 ? (
            <EmptyState
              title="No consents recorded"
              hint="Consents are captured when the patient gives permission on a channel."
            />
          ) : (
            <Table headers={["Purpose", "Channel", "Status", "Captured"]} empty="No consents.">
              {list.map((consent) => (
                <tr key={consent.id}>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-primary)" }}>
                    {consent.purpose}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {consent.channel}
                  </td>
                  <td className="px-4 py-3">
                    <Badge
                      tone={
                        consent.consent_status === "granted"
                          ? "success"
                          : consent.consent_status === "withdrawn"
                            ? "danger"
                            : "warning"
                      }
                    >
                      {consent.consent_status}
                    </Badge>
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {formatDateTime(consent.captured_at)}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </div>
    </Modal>
  );
}

export default function PatientsPage() {
  const { activeClinicId } = useAuth();
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<Patient | null>(null);

  const { data, error, loading, reload } = useApiData<{ patients: Paginated<Patient> }>(
    async (api, signal) => {
      const patients = await api.get<Paginated<Patient>>("/patients/", { signal });
      return { patients };
    },
    activeClinicId ?? "patients",
  );

  const rows = useMemo(() => {
    const list = data?.patients.results ?? [];
    if (!search.trim()) return list;
    const needle = search.trim().toLowerCase();
    return list.filter(
      (patient) =>
        patient.name?.toLowerCase().includes(needle) || patient.phone?.includes(needle),
    );
  }, [data, search]);

  if (loading) return <Spinner label="Loading patients…" size="lg" />;
  if (error) return <ErrorBanner error={error} />;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Patients</h1>
          <p className="page-subtitle">
            {data?.patients.count ?? 0} patient{data?.patients.count === 1 ? "" : "s"} on record.
          </p>
        </div>
        <Button variant="primary" onClick={() => setAdding(true)}>
          Add patient
        </Button>
      </header>

      <Card
        title="Register"
        action={
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by name or phone"
            aria-label="Search patients"
            style={{ width: "16rem" }}
          />
        }
      >
        {rows.length === 0 ? (
          <EmptyState
            title="No patients found"
            hint="Add a patient, or search with a different name or number."
            action={
              <Button variant="primary" onClick={() => setAdding(true)}>
                Add patient
              </Button>
            }
          />
        ) : (
          <Table headers={["Name", "Phone", "Language", "Reachable on", ""]} empty="No patients.">
            {rows.map((patient) => {
              const channels = CHANNELS.filter((channel) => patientPrefers(patient, channel));
              return (
                <tr key={patient.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium" style={{ color: "var(--color-text-primary)" }}>
                      {patient.name || "Unnamed patient"}
                    </p>
                    {!patient.is_active ? (
                      <Badge tone="neutral">Inactive</Badge>
                    ) : null}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {patient.phone}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {patient.preferred_language || "—"}
                  </td>
                  <td className="px-4 py-3">
                    {channels.length ? (
                      <div className="flex flex-wrap gap-1">
                        {channels.map((channel) => (
                          <Badge key={channel} tone="neutral">
                            {channel}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <Badge tone="danger">No channel</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Button variant="ghost" onClick={() => setSelected(patient)}>
                      Open
                    </Button>
                  </td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>

      <PatientModal isOpen={adding} onClose={() => setAdding(false)} onSaved={reload} />
      <PatientDetail patient={selected} onClose={() => setSelected(null)} />
    </div>
  );
}