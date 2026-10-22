"use client";

/**
 * The call log.
 *
 * This screen deliberately does not show transcripts. The models carry a
 * reference to retained content rather than the content itself, so what a
 * receptionist sees here is the operational picture: who called, how long,
 * and what came of it.
 */
import { useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  Select,
  Spinner,
  Table,
} from "@/components/ui";
import { formatDateTime, formatDuration, humanise } from "@/lib/format";
import type { CallLog, Conversation, Paginated } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

const OUTCOME_OPTIONS = [
  { value: "", label: "All outcomes" },
  { value: "resolved", label: "Resolved" },
  { value: "booked", label: "Booked" },
  { value: "escalated", label: "Escalated" },
  { value: "unresolved", label: "Unresolved" },
  { value: "abandoned", label: "Abandoned" },
  { value: "failed", label: "Failed" },
  { value: "out_of_hours", label: "Out of hours" },
];

const OUTCOME_TONE: Record<string, "success" | "warning" | "danger" | "neutral" | "info"> = {
  resolved: "success",
  booked: "success",
  escalated: "warning",
  unresolved: "warning",
  abandoned: "neutral",
  failed: "danger",
  out_of_hours: "neutral",
};

export default function CallsPage() {
  const { activeClinic, activeClinicId } = useAuth();
  const timezone = activeClinic?.timezone;

  const [outcome, setOutcome] = useState("");
  const [view, setView] = useState<"calls" | "conversations">("calls");

  const { data, error, loading } = useApiData<{
    calls: Paginated<CallLog>;
    conversations: Paginated<Conversation>;
  }>(async (api, signal) => {
    const [calls, conversations] = await Promise.all([
      api.get<Paginated<CallLog>>("/call-logs/", {
        params: outcome ? { outcome } : undefined,
        signal,
      }),
      api.get<Paginated<Conversation>>("/conversations/", {
        params: outcome ? { outcome } : undefined,
        signal,
      }),
    ]);
    return { calls, conversations };
  }, `${activeClinicId ?? ""}:${outcome}:${view}`);

  const totalSeconds = useMemo(
    () =>
      (data?.calls.results ?? []).reduce((sum, call) => sum + (call.duration_seconds ?? 0), 0),
    [data],
  );

  if (loading) return <Spinner label="Loading call activity…" size="lg" />;
  if (error) return <ErrorBanner error={error} />;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Calls</h1>
          <p className="page-subtitle">
            Every call the assistant handled, and every conversation it left open.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div
            className="flex p-0.5"
            style={{
              backgroundColor: "var(--color-surface-subtle)",
              borderRadius: "var(--radius-card)",
            }}
          >
            {(["calls", "conversations"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setView(option)}
                aria-pressed={view === option}
                className="btn"
                style={{
                  height: "2rem",
                  padding: "0 0.75rem",
                  backgroundColor: view === option ? "var(--color-surface-elevated)" : "transparent",
                  color: view === option ? "var(--color-text-primary)" : "var(--color-text-secondary)",
                  boxShadow: view === option ? "0 1px 2px 0 rgb(15 23 42 / 0.05)" : "none",
                }}
              >
                {option === "calls" ? "Call log" : "Conversations"}
              </button>
            ))}
          </div>
          <Select
            value={outcome}
            onChange={(event) => setOutcome(event.target.value)}
            aria-label="Filter by outcome"
            style={{ width: "12rem" }}
          >
            {OUTCOME_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </div>
      </header>

      {view === "calls" ? (
        <Card
          title="Call log"
          subtitle={
            data
              ? `${data.calls.count} call${data.calls.count === 1 ? "" : "s"} recorded · ${formatDuration(totalSeconds)} of talk time`
              : undefined
          }
        >
          {!data || data.calls.results.length === 0 ? (
            <EmptyState
              title="No calls recorded"
              hint="Calls appear here once the telephony provider reports them."
            />
          ) : (
            <Table headers={["Started", "Direction", "From", "Duration", "Outcome", "Detail"]} empty="No calls.">
              {data.calls.results.map((call) => (
                <tr key={call.id}>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {call.started_at
                      ? formatDateTime(call.started_at, timezone)
                      : formatDateTime(call.created_at, timezone)}
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone="neutral">{humanise(call.direction)}</Badge>
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {call.from_number || call.to_number || "—"}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {formatDuration(call.duration_seconds)}
                  </td>
                  <td className="px-4 py-3">
                    {call.outcome ? (
                      <Badge tone={OUTCOME_TONE[call.outcome] ?? "neutral"}>{humanise(call.outcome)}</Badge>
                    ) : (
                      <Badge tone="neutral">Unknown</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-muted)" }}>
                    {call.failure_reason || "—"}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      ) : (
        <Card
          title="Conversations"
          subtitle={
            data
              ? `${data.conversations.count} conversation${data.conversations.count === 1 ? "" : "s"}`
              : undefined
          }
        >
          {!data || data.conversations.results.length === 0 ? (
            <EmptyState
              title="No conversations"
              hint="Voice, WhatsApp and SMS interactions appear here."
            />
          ) : (
            <Table headers={["Started", "Channel", "Status", "Outcome", "Summary"]} empty="No conversations.">
              {data.conversations.results.map((conversation) => (
                <tr key={conversation.id}>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {formatDateTime(conversation.started_at ?? conversation.created_at, timezone)}
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone="neutral">{humanise(conversation.channel)}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge
                      tone={
                        conversation.status === "escalated"
                          ? "warning"
                          : conversation.status === "closed"
                            ? "neutral"
                            : "info"
                      }
                    >
                      {humanise(conversation.status)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {conversation.outcome ? humanise(conversation.outcome) : "—"}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-muted)" }}>
                    {conversation.summary || "—"}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}
    </div>
  );
}