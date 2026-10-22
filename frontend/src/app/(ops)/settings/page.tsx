"use client";

/**
 * Clinic settings.
 *
 * Everything on this page changes how the assistant behaves for the whole
 * clinic: when it is open, how far ahead it books, when it reminds people,
 * and when it hands over to a human. It is the one page where a change
 * affects everybody, so it is admin-only.
 */
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  Select,
  Spinner,
  Table,
} from "@/components/ui";
import { formatDateTime, humanise } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";

const WEEKDAYS = [
  { key: "mon", label: "Monday" },
  { key: "tue", label: "Tuesday" },
  { key: "wed", label: "Wednesday" },
  { key: "thu", label: "Thursday" },
  { key: "fri", label: "Friday" },
  { key: "sat", label: "Saturday" },
  { key: "sun", label: "Sunday" },
];

const STATUS_FRESHNESS_KEYS = [
  "present",
  "running_late",
  "unavailable",
  "on_leave",
  "finished_for_day",
  "scheduled",
];

interface ClinicSettingsShape {
  operating_hours: Record<string, { open: string; close: string; closed: boolean }>;
  default_language: string;
  supported_languages: string[];
  appointment_rules: Record<string, unknown>;
  reminder_policy: Record<string, unknown>;
  escalation_policy: Record<string, unknown>;
  status_freshness_minutes: Record<string, number>;
  privacy_notice_url: string;
  updated_at: string;
}

interface Membership {
  id: string;
  user_email: string;
  user_name: string;
  role: string;
  status: string;
  created_at: string;
}

interface ChannelNumber {
  id: string;
  channel: string;
  display_number: string;
  routing_status: string;
  capabilities: string[];
}

export default function SettingsPage() {
  const { api, activeClinic, activeClinicId } = useAuth();
  const role = activeClinic?.role;
  const isAdmin = role === "clinic_admin";

  const [tab, setTab] = useState<"hours" | "rules" | "staff" | "channels">("hours");
  const [draft, setDraft] = useState<ClinicSettingsShape | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  const { data, error, loading, reload } = useApiData<{
    settings: ClinicSettingsShape;
    members: Membership[];
    numbers: ChannelNumber[];
  }>(async (apiClient, signal) => {
    if (!activeClinicId) return { settings: null as never, members: [], numbers: [] };
    const [settings, members, numbers] = await Promise.all([
      apiClient.get<ClinicSettingsShape>(`/clinics/${activeClinicId}/settings/`, { signal }),
      apiClient.get<Membership[]>(`/clinics/${activeClinicId}/members/`, { signal }),
      apiClient.get<ChannelNumber[]>(`/clinics/${activeClinicId}/channel-numbers/`, { signal }),
    ]);
    return { settings, members: members ?? [], numbers: numbers ?? [] };
  }, activeClinicId ?? "settings");

  // Keep a local draft so edits are not lost while typing.
  useEffect(() => {
    if (data?.settings) setDraft(data.settings);
  }, [data]);

  useEffect(() => {
    if (!saved) return;
    const timer = setTimeout(() => setSaved(false), 4000);
    return () => clearTimeout(timer);
  }, [saved]);

  async function save() {
    if (!draft || !activeClinicId) return;
    setBusy(true);
    setSaveError(null);
    try {
      await api.patch(`/clinics/${activeClinicId}/settings/`, {
        operating_hours: draft.operating_hours,
        default_language: draft.default_language,
        supported_languages: draft.supported_languages,
        appointment_rules: draft.appointment_rules,
        reminder_policy: draft.reminder_policy,
        escalation_policy: draft.escalation_policy,
        status_freshness_minutes: draft.status_freshness_minutes,
        privacy_notice_url: draft.privacy_notice_url,
      });
      setSaved(true);
      reload();
    } catch (cause) {
      setSaveError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function addMember(email: string, memberRole: string) {
    if (!activeClinicId) return;
    setBusy(true);
    setSaveError(null);
    try {
      await api.post(`/clinics/${activeClinicId}/members/`, {
        email,
        role: memberRole,
      });
      reload();
    } catch (cause) {
      setSaveError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner label="Loading clinic settings…" size="lg" />;
  if (error) return <ErrorBanner error={error} />;
  if (!draft) return <ErrorBanner error={new Error("Clinic settings are not available.")} />;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Clinic settings</h1>
          <p className="page-subtitle">
            {activeClinic?.name} · {activeClinic?.timezone}. These rules apply to everybody in
            this clinic.
          </p>
        </div>
        {isAdmin ? (
          <Button variant="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save changes"}
          </Button>
        ) : null}
      </header>

      {!isAdmin ? (
        <div
          className="mb-6 px-4 py-3 text-body-sm"
          style={{
            backgroundColor: "var(--color-warning-light)",
            color: "var(--color-warning)",
            borderRadius: "var(--radius-card)",
          }}
        >
          Only a clinic administrator can change these settings. You can look, but not edit.
        </div>
      ) : null}

      {saveError ? (
        <div style={{ marginBottom: "var(--space-section)" }}>
          <ErrorBanner error={saveError} />
        </div>
      ) : null}

      {saved ? (
        <div
          className="mb-6 px-4 py-3 text-body-sm"
          style={{
            backgroundColor: "var(--color-success-light)",
            color: "var(--color-success)",
            borderRadius: "var(--radius-card)",
          }}
          role="status"
        >
          Settings saved.
        </div>
      ) : null}

      {/* Tabs ------------------------------------------------------- */}
      <div
        className="mb-6 flex flex-wrap gap-1 p-1"
        style={{
          backgroundColor: "var(--color-surface-subtle)",
          borderRadius: "var(--radius-card)",
          width: "fit-content",
        }}
      >
        {(
          [
            { value: "hours" as const, label: "Opening hours" },
            { value: "rules" as const, label: "Booking & reminders" },
            { value: "staff" as const, label: "Staff" },
            { value: "channels" as const, label: "Channels" },
          ]
        ).map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => setTab(option.value)}
            aria-pressed={tab === option.value}
            className="btn"
            style={{
              height: "2.25rem",
              backgroundColor:
                tab === option.value ? "var(--color-surface-elevated)" : "transparent",
              color:
                tab === option.value
                  ? "var(--color-text-primary)"
                  : "var(--color-text-secondary)",
              boxShadow: tab === option.value ? "0 1px 2px 0 rgb(15 23 42 / 0.06)" : "none",
            }}
          >
            {option.label}
          </button>
        ))}
      </div>

      {tab === "hours" ? (
        <Card
          title="Opening hours"
          subtitle="The assistant stops offering slots outside these hours and routes out-of-hours calls to a follow-up."
        >
          <div className="space-y-3">
            {WEEKDAYS.map((day) => {
              const window = draft.operating_hours?.[day.key] ?? {
                open: "09:00",
                close: "19:00",
                closed: false,
              };
              return (
                <div
                  key={day.key}
                  className="flex flex-wrap items-center gap-3 px-4 py-3"
                  style={{
                    border: "1px solid var(--color-border-subtle)",
                    borderRadius: "var(--radius-card)",
                  }}
                >
                  <label className="flex w-40 items-center gap-2 text-body-sm">
                    <input
                      type="checkbox"
                      checked={!window.closed}
                      disabled={!isAdmin}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          operating_hours: {
                            ...draft.operating_hours,
                            [day.key]: { ...window, closed: !event.target.checked },
                          },
                        })
                      }
                    />
                    {day.label}
                  </label>

                  {window.closed ? (
                    <Badge tone="neutral">Closed</Badge>
                  ) : (
                    <div className="flex items-center gap-2">
                      <Input
                        type="time"
                        value={window.open}
                        disabled={!isAdmin}
                        aria-label={`${day.label} opening time`}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            operating_hours: {
                              ...draft.operating_hours,
                              [day.key]: { ...window, open: event.target.value },
                            },
                          })
                        }
                        style={{ width: "9rem" }}
                      />
                      <span className="text-caption" style={{ color: "var(--color-text-muted)" }}>
                        to
                      </span>
                      <Input
                        type="time"
                        value={window.close}
                        disabled={!isAdmin}
                        aria-label={`${day.label} closing time`}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            operating_hours: {
                              ...draft.operating_hours,
                              [day.key]: { ...window, close: event.target.value },
                            },
                          })
                        }
                        style={{ width: "9rem" }}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      ) : null}

      {tab === "rules" ? (
        <div className="space-y-6">
          <Card
            title="Appointment rules"
            subtitle="How far ahead patients may book, and how long a slot lasts."
          >
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Slot interval (minutes)">
                <Input
                  type="number"
                  min={5}
                  max={240}
                  disabled={!isAdmin}
                  value={String(draft.appointment_rules.slot_interval_minutes ?? 30)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      appointment_rules: {
                        ...draft.appointment_rules,
                        slot_interval_minutes: Number(event.target.value),
                      },
                    })
                  }
                />
              </Field>
              <Field label="Appointment duration (minutes)">
                <Input
                  type="number"
                  min={5}
                  max={240}
                  disabled={!isAdmin}
                  value={String(draft.appointment_rules.appointment_duration_minutes ?? 30)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      appointment_rules: {
                        ...draft.appointment_rules,
                        appointment_duration_minutes: Number(event.target.value),
                      },
                    })
                  }
                />
              </Field>
              <Field label="Buffer between slots (minutes)">
                <Input
                  type="number"
                  min={0}
                  max={120}
                  disabled={!isAdmin}
                  value={String(draft.appointment_rules.buffer_minutes ?? 10)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      appointment_rules: {
                        ...draft.appointment_rules,
                        buffer_minutes: Number(event.target.value),
                      },
                    })
                  }
                />
              </Field>
              <Field label="Booking horizon (days)">
                <Input
                  type="number"
                  min={1}
                  max={365}
                  disabled={!isAdmin}
                  value={String(draft.appointment_rules.booking_horizon_days ?? 30)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      appointment_rules: {
                        ...draft.appointment_rules,
                        booking_horizon_days: Number(event.target.value),
                      },
                    })
                  }
                />
              </Field>
              <Field label="Cancellation window (hours)">
                <Input
                  type="number"
                  min={0}
                  max={168}
                  disabled={!isAdmin}
                  value={String(draft.appointment_rules.cancellation_window_hours ?? 4)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      appointment_rules: {
                        ...draft.appointment_rules,
                        cancellation_window_hours: Number(event.target.value),
                      },
                    })
                  }
                />
              </Field>
              <Field label="Same-day booking">
                <Select
                  disabled={!isAdmin}
                  value={String(draft.appointment_rules.allow_same_day_booking ?? true)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      appointment_rules: {
                        ...draft.appointment_rules,
                        allow_same_day_booking: event.target.value === "true",
                      },
                    })
                  }
                >
                  <option value="true">Allowed</option>
                  <option value="false">Not allowed</option>
                </Select>
              </Field>
            </div>
          </Card>

          <Card
            title="Reminder policy"
            subtitle="When the assistant reminds a patient, on which channel, and how hard it tries."
          >
            <div className="grid gap-5 sm:grid-cols-2">
              <Field
                label="Reminder offsets (hours before)"
                hint="Comma separated, earliest first."
              >
                <Input
                  disabled={!isAdmin}
                  value={((draft.reminder_policy.offsets_hours as number[] | undefined) ?? [24, 2]).join(", ")}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      reminder_policy: {
                        ...draft.reminder_policy,
                        offsets_hours: event.target.value
                          .split(",")
                          .map((value) => Number(value.trim()))
                          .filter((value) => Number.isFinite(value)),
                      },
                    })
                  }
                />
              </Field>
              <Field label="Channels" hint="Comma separated, e.g. sms, whatsapp.">
                <Input
                  disabled={!isAdmin}
                  value={((draft.reminder_policy.channels as string[] | undefined) ?? ["sms", "whatsapp"]).join(", ")}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      reminder_policy: {
                        ...draft.reminder_policy,
                        channels: event.target.value
                          .split(",")
                          .map((value) => value.trim())
                          .filter(Boolean),
                      },
                    })
                  }
                />
              </Field>
              <Field label="Maximum attempts">
                <Input
                  type="number"
                  min={1}
                  max={10}
                  disabled={!isAdmin}
                  value={String(draft.reminder_policy.max_attempts ?? 3)}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      reminder_policy: {
                        ...draft.reminder_policy,
                        max_attempts: Number(event.target.value),
                      },
                    })
                  }
                />
              </Field>
            </div>
          </Card>

          <Card
            title="Status freshness"
            subtitle="How long a doctor's status stays trustworthy before it is treated as unknown."
          >
            <div className="grid gap-5 sm:grid-cols-2">
              {STATUS_FRESHNESS_KEYS.map((key) => (
                <Field key={key} label={humanise(key)}>
                  <Input
                    type="number"
                    min={0}
                    max={1440}
                    disabled={!isAdmin}
                    value={String(draft.status_freshness_minutes[key] ?? 0)}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        status_freshness_minutes: {
                          ...draft.status_freshness_minutes,
                          [key]: Number(event.target.value),
                        },
                      })
                    }
                  />
                </Field>
              ))}
            </div>
          </Card>

          <Card title="Languages and privacy" subtitle="How the assistant greets patients.">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Default language">
                <Input
                  disabled={!isAdmin}
                  value={draft.default_language}
                  onChange={(event) => setDraft({ ...draft, default_language: event.target.value })}
                />
              </Field>
              <Field label="Supported languages" hint="Comma separated, e.g. hi-IN, en-IN, ta-IN.">
                <Input
                  disabled={!isAdmin}
                  value={(draft.supported_languages ?? []).join(", ")}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      supported_languages: event.target.value
                        .split(",")
                        .map((value) => value.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </Field>
              <Field label="Privacy notice URL" hint="Shown to patients before their data is used.">
                <Input
                  disabled={!isAdmin}
                  value={draft.privacy_notice_url}
                  onChange={(event) => setDraft({ ...draft, privacy_notice_url: event.target.value })}
                  placeholder="https://example.com/privacy"
                />
              </Field>
            </div>
          </Card>
        </div>
      ) : null}

      {tab === "staff" ? (
        <Card
          title="Staff"
          subtitle="Everybody with access to this clinic. Add a person by the email address they registered with."
        >
          <StaffManager
            members={data?.members ?? []}
            isAdmin={isAdmin}
            busy={busy}
            onAdd={addMember}
          />
        </Card>
      ) : null}

      {tab === "channels" ? (
        <Card
          title="Channels"
          subtitle="The numbers and channels patients can reach this clinic on."
        >
          {!data || data.numbers.length === 0 ? (
            <EmptyState
              title="No channels connected"
              hint="A provider administrator connects the voice, WhatsApp and SMS numbers for this clinic."
            />
          ) : (
            <Table headers={["Channel", "Number", "Routing", "Capabilities"]} empty="No channels.">
              {data.numbers.map((number) => (
                <tr key={number.id}>
                  <td className="px-4 py-3">
                    <Badge tone="neutral">{humanise(number.channel)}</Badge>
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-primary)" }}>
                    {number.display_number || number.id}
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={number.routing_status === "active" ? "success" : "warning"}>
                      {humanise(number.routing_status)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {number.capabilities?.length ? number.capabilities.join(", ") : "—"}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      ) : null}
    </div>
  );
}

function StaffManager({
  members,
  isAdmin,
  busy,
  onAdd,
}: {
  members: Membership[];
  isAdmin: boolean;
  busy: boolean;
  onAdd: (email: string, role: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("receptionist");

  return (
    <div className="space-y-6">
      {isAdmin ? (
        <div
          className="flex flex-wrap items-end gap-3 pb-6"
          style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
        >
          <div className="min-w-[16rem] flex-1">
            <Field
              label="Add a person"
              hint="They must already have an account with this email address."
            >
              <Input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="colleague@clinic.example"
              />
            </Field>
          </div>
          <div className="w-44">
            <Field label="Role">
              <Select value={role} onChange={(event) => setRole(event.target.value)}>
                <option value="clinic_admin">Clinic admin</option>
                <option value="doctor">Doctor</option>
                <option value="receptionist">Receptionist</option>
              </Select>
            </Field>
          </div>
          <Button
            variant="primary"
            disabled={busy || !email.trim()}
            onClick={() => onAdd(email.trim(), role)}
          >
            {busy ? "Adding…" : "Add to clinic"}
          </Button>
        </div>
      ) : null}

      {members.length === 0 ? (
        <EmptyState title="No staff yet" hint="Add the people who work at this clinic." />
      ) : (
        <Table headers={["Name", "Email", "Role", "Status", "Joined"]} empty="No staff.">
          {members.map((member) => (
            <tr key={member.id}>
              <td className="px-4 py-3" style={{ color: "var(--color-text-primary)" }}>
                {member.user_name || "—"}
              </td>
              <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                {member.user_email}
              </td>
              <td className="px-4 py-3">
                <Badge tone={member.role === "clinic_admin" ? "brand" : "neutral"}>
                  {humanise(member.role)}
                </Badge>
              </td>
              <td className="px-4 py-3">
                <Badge tone={member.status === "active" ? "success" : "neutral"}>
                  {humanise(member.status)}
                </Badge>
              </td>
              <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                {formatDateTime(member.created_at)}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </div>
  );
}
