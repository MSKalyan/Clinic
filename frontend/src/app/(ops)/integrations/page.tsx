"use client";

/**
 * The integrations page.
 *
 * Every clinic brings its own provider accounts: its own WhatsApp
 * business number, its own voice agent, its own telephony account. This
 * screen says, for each key the platform needs, whether the clinic has
 * set it -- and lets them set the ones that are missing.
 *
 * Two rules the screen is built around:
 *
 *   1. **A secret is never shown again.** The status column says "Set" or
 *      "Not set" and shows a fingerprint, never the value.
 *   2. **Only a clinic admin sees this.** The API enforces that too, so
 *      hiding the link is a courtesy, not the security boundary.
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
  Modal,
  Spinner,
  Textarea,
} from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import type { ClinicConfiguration, ConfigKey } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

function StatusBadge({ item }: { item: ConfigKey }) {
  if (item.status === "set") {
    return <Badge tone="success">Set by your clinic</Badge>;
  }
  if (item.status === "platform") {
    return <Badge tone="info">Platform default</Badge>;
  }
  return <Badge tone={item.required ? "danger" : "warning"}>Not set</Badge>;
}

function SetKeyModal({
  item,
  onClose,
  onSaved,
}: {
  item: ConfigKey | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { api, activeClinicId } = useAuth();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (!item) return null;

  async function save() {
    if (!item || !activeClinicId) return;
    if (!value.trim()) {
      setError(new Error("Enter the value for this key."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.put(`/clinics/${activeClinicId}/configuration/${item.key}/`, {
        value: value.trim(),
      });
      setValue("");
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
      isOpen={Boolean(item)}
      onClose={onClose}
      title={item.label}
      action={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save key"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {error ? <ErrorBanner error={error} /> : null}

        <p className="text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
          {item.purpose}
        </p>

        <Field
          label="Value"
          hint="Stored encrypted. It is never shown again — only whether it is set."
        >
          <Textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Paste the value"
            rows={3}
            autoFocus
            disabled={busy}
            spellCheck={false}
            autoComplete="off"
            style={{ fontFamily: "var(--font-mono)" }}
          />
        </Field>

        {item.status === "platform" ? (
          <p
            className="px-3 py-2 text-body-sm"
            style={{
              backgroundColor: "var(--color-info-light)",
              color: "var(--color-info)",
              borderRadius: "var(--radius-card)",
            }}
          >
            The platform already has a default for this key. Saving yours replaces it for this
            clinic only.
          </p>
        ) : null}

        {item.fingerprint ? (
          <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
            Currently stored: {item.fingerprint}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}

export default function IntegrationsPage() {
  const { api, activeClinic, activeClinicId } = useAuth();
  const role = activeClinic?.role;
  const isAdmin = role === "clinic_admin";

  const [editing, setEditing] = useState<ConfigKey | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const { data, error, loading, reload } = useApiData<ClinicConfiguration>(
    async (apiClient, signal) => {
      const configuration = await apiClient.get<ClinicConfiguration>(
        `/clinics/${activeClinicId}/configuration/`,
        { signal },
      );
      return configuration;
    },
    activeClinicId ?? "configuration",
  );

  const grouped = useMemo(() => {
    if (!data) return [];
    return data.groups
      .map((group) => ({
        ...group,
        items: data.keys.filter((item) => item.group === group.key),
      }))
      .filter((group) => group.items.length > 0);
  }, [data]);

  async function removeKey(item: ConfigKey) {
    if (!activeClinicId) return;
    setBusyKey(item.key);
    setActionError(null);
    try {
      await api.delete(`/clinics/${activeClinicId}/configuration/${item.key}/`);
      reload();
    } catch (cause) {
      setActionError(cause);
    } finally {
      setBusyKey(null);
    }
  }

  if (loading) return <Spinner label="Checking your configuration…" size="lg" />;
  if (error) return <ErrorBanner error={error} />;

  if (!isAdmin) {
    return (
      <div className="page">
        <header className="page-header">
          <div>
            <h1 className="page-title">Integrations</h1>
            <p className="page-subtitle">Provider accounts and credentials for this clinic.</p>
          </div>
        </header>
        <EmptyState
          title="Only a clinic administrator can see this"
          hint="Ask the clinic administrator if you need to change a provider key."
        />
      </div>
    );
  }

  const summary = data?.summary;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Integrations</h1>
          <p className="page-subtitle">
            {activeClinic?.name}&apos;s own provider credentials. A key you set here applies to
            this clinic only.
          </p>
        </div>
        <Button variant="secondary" onClick={reload}>
          Re-check
        </Button>
      </header>

      {actionError ? (
        <div style={{ marginBottom: "var(--space-section)" }}>
          <ErrorBanner error={actionError} />
        </div>
      ) : null}

      {summary && summary.missing_required > 0 ? (
        <div
          className="mb-6 px-4 py-3 text-body-sm"
          style={{
            backgroundColor: "var(--color-danger-light)",
            color: "var(--color-danger)",
            borderRadius: "var(--radius-card)",
          }}
        >
          {summary.missing_required} required key{summary.missing_required === 1 ? " is" : "s are"}{" "}
          still missing. Until they are set, the features that need them will not work for this
          clinic.
        </div>
      ) : summary ? (
        <div
          className="mb-6 px-4 py-3 text-body-sm"
          style={{
            backgroundColor: "var(--color-success-light)",
            color: "var(--color-success)",
            borderRadius: "var(--radius-card)",
          }}
        >
          Everything this clinic needs is set.
        </div>
      ) : null}

      {grouped.map((group) => (
        <Card
          key={group.key}
          title={group.label}
          subtitle={
            group.key === "platform"
              ? "Set by whoever runs the platform, not by the clinic."
              : undefined
          }
          className="mb-6"
        >
          <div className="table-wrapper">
            <table className="table table-dense">
              <thead>
                <tr>
                  <th style={{ width: "18rem" }}>Key</th>
                  <th>What it does</th>
                  <th style={{ width: "11rem" }}>Status</th>
                  <th style={{ width: "12rem" }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {group.items.map((item) => (
                  <tr key={item.key}>
                    <td className="px-4 py-3">
                      <p className="font-medium" style={{ color: "var(--color-text-primary)" }}>
                        {item.label}
                      </p>
                      <p
                        className="text-caption"
                        style={{ color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}
                      >
                        {item.env_var}
                      </p>
                    </td>
                    <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                      {item.purpose}
                      {item.fingerprint ? (
                        <p
                          className="text-caption mt-0.5"
                          style={{ color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}
                        >
                          {item.fingerprint}
                        </p>
                      ) : null}
                      {item.updated_at ? (
                        <p className="text-caption mt-0.5" style={{ color: "var(--color-text-muted)" }}>
                          Updated {formatDateTime(item.updated_at)}
                        </p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge item={item} />
                    </td>
                    <td className="px-4 py-3">
                      {item.editable ? (
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            onClick={() => setEditing(item)}
                            aria-label={`${item.status === "set" ? "Replace" : "Set"} ${item.label}`}
                          >
                            {item.status === "set" ? "Replace" : "Set"}
                          </Button>
                          {item.status === "set" ? (
                            <Button
                              variant="ghost"
                              onClick={() => removeKey(item)}
                              disabled={busyKey === item.key}
                              aria-label={`Remove ${item.label}`}
                            >
                              {busyKey === item.key ? "…" : "Remove"}
                            </Button>
                          ) : null}
                        </div>
                      ) : (
                        <span className="text-caption" style={{ color: "var(--color-text-muted)" }}>
                          Platform setting
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}

      <SetKeyModal item={editing} onClose={() => setEditing(null)} onSaved={reload} />
    </div>
  );
}
