"use client";

/**
 * Conversations.
 *
 * The conversation list is the clinic's view of every patient interaction
 * across voice, WhatsApp and SMS. Opening one shows the turns of the
 * conversation -- the retained excerpt, not a full transcript.
 */
import { useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Modal,
  Select,
  Spinner,
  Table,
} from "@/components/ui";
import { formatDateTime, humanise } from "@/lib/format";
import type { Conversation, ConversationMessage, Paginated } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

const CHANNEL_OPTIONS = [
  { value: "", label: "All channels" },
  { value: "voice", label: "Voice" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "sms", label: "SMS" },
];

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "escalated", label: "Escalated" },
  { value: "closed", label: "Closed" },
];

const OUTCOME_OPTIONS = [
  { value: "", label: "All outcomes" },
  { value: "resolved", label: "Resolved" },
  { value: "booked", label: "Booked" },
  { value: "escalated", label: "Escalated" },
  { value: "unresolved", label: "Unresolved" },
  { value: "abandoned", label: "Abandoned" },
  { value: "out_of_hours", label: "Out of hours" },
];

const STATUS_TONE: Record<string, "info" | "warning" | "neutral" | "success"> = {
  open: "info",
  escalated: "warning",
  closed: "neutral",
  handed_off: "warning",
};

export default function ConversationsPage() {
  const { activeClinic, activeClinicId } = useAuth();
  const timezone = activeClinic?.timezone;

  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [outcome, setOutcome] = useState("");
  const [selected, setSelected] = useState<Conversation | null>(null);

  const { data, error, loading } = useApiData<{ conversations: Paginated<Conversation> }>(
    async (api, signal) => {
      const params: Record<string, string> = {};
      if (channel) params.channel = channel;
      if (status) params.status = status;
      if (outcome) params.outcome = outcome;
      const conversations = await api.get<Paginated<Conversation>>("/conversations/", {
        params,
        signal,
      });
      return { conversations };
    },
    `${activeClinicId ?? ""}:${channel}:${status}:${outcome}`,
  );

  const rows = useMemo(() => data?.conversations.results ?? [], [data]);

  if (loading) return <Spinner label="Loading conversations…" size="lg" />;
  if (error) return <ErrorBanner error={error} />;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Conversations</h1>
          <p className="page-subtitle">
            {data?.conversations.count ?? 0} interaction
            {data?.conversations.count === 1 ? "" : "s"} across every channel.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select
            value={channel}
            onChange={(event) => setChannel(event.target.value)}
            aria-label="Filter by channel"
            style={{ width: "10rem" }}
          >
            {CHANNEL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
          <Select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            aria-label="Filter by status"
            style={{ width: "10rem" }}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
          <Select
            value={outcome}
            onChange={(event) => setOutcome(event.target.value)}
            aria-label="Filter by outcome"
            style={{ width: "11rem" }}
          >
            {OUTCOME_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </div>
      </header>

      <Card title="Interactions" subtitle="Newest first. Open one to read the turns.">
        {rows.length === 0 ? (
          <EmptyState
            title="No conversations match this view"
            hint="Calls, WhatsApp messages and texts appear here as the assistant handles them."
          />
        ) : (
          <Table headers={["Started", "Channel", "Status", "Outcome", "Summary", ""]} empty="No conversations.">
            {rows.map((conversation) => (
              <tr key={conversation.id}>
                <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                  {formatDateTime(conversation.started_at ?? conversation.created_at, timezone)}
                </td>
                <td className="px-4 py-3">
                  <Badge tone="neutral">{humanise(conversation.channel)}</Badge>
                </td>
                <td className="px-4 py-3">
                  <Badge tone={STATUS_TONE[conversation.status] ?? "neutral"}>
                    {humanise(conversation.status)}
                  </Badge>
                </td>
                <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                  {conversation.outcome ? humanise(conversation.outcome) : "—"}
                </td>
                <td
                  className="px-4 py-3"
                  style={{
                    color: "var(--color-text-muted)",
                    maxWidth: "24rem",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {conversation.summary || "—"}
                </td>
                <td className="px-4 py-3">
                  <Button variant="ghost" onClick={() => setSelected(conversation)}>
                    Open
                  </Button>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {selected ? (
        <ConversationDetail
          conversation={selected}
          timezone={timezone}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}

function ConversationDetail({
  conversation,
  timezone,
  onClose,
}: {
  conversation: Conversation;
  timezone: string | undefined;
  onClose: () => void;
}) {
  const { data, error, loading } = useApiData<{
    conversation: Conversation;
    messages: ConversationMessage[];
  }>(async (api, signal) => {
    const payload = await api.get<{
      conversation: Conversation;
      messages: ConversationMessage[];
    }>(`/conversations/${conversation.id}/`, { signal });
    return payload;
  }, conversation.id);

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`${humanise(conversation.channel)} conversation`}
      action={
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={STATUS_TONE[conversation.status] ?? "neutral"}>
            {humanise(conversation.status)}
          </Badge>
          {conversation.outcome ? (
            <Badge tone="neutral">{humanise(conversation.outcome)}</Badge>
          ) : null}
          <span className="text-caption" style={{ color: "var(--color-text-muted)" }}>
            {formatDateTime(conversation.started_at ?? conversation.created_at, timezone)}
          </span>
        </div>

        {conversation.summary ? (
          <div
            className="px-4 py-3 text-body-sm"
            style={{
              backgroundColor: "var(--color-surface-subtle)",
              borderRadius: "var(--radius-card)",
              color: "var(--color-text-secondary)",
            }}
          >
            {conversation.summary}
          </div>
        ) : null}

        {conversation.escalation_reason ? (
          <div
            className="px-4 py-3 text-body-sm"
            style={{
              backgroundColor: "var(--color-warning-light)",
              color: "var(--color-warning)",
              borderRadius: "var(--radius-card)",
            }}
          >
            Escalated: {conversation.escalation_reason}
          </div>
        ) : null}

        {loading ? (
          <Spinner label="Loading the conversation…" />
        ) : error ? (
          <ErrorBanner error={error} />
        ) : !data || data.messages.length === 0 ? (
          <EmptyState
            title="No retained turns"
            hint="Transcripts are not kept indefinitely. The operational summary above is what remains."
          />
        ) : (
          <ol className="space-y-3">
            {data.messages.map((message) => (
              <li key={message.id}>
                <div className="mb-1 flex items-center gap-2">
                  <Badge tone={message.direction === "inbound" ? "info" : "neutral"}>
                    {humanise(message.direction)}
                  </Badge>
                  <span className="text-caption" style={{ color: "var(--color-text-muted)" }}>
                    {formatDateTime(message.created_at, timezone)}
                  </span>
                </div>
                <p
                  className="px-3 py-2 text-body-sm"
                  style={{
                    backgroundColor:
                      message.direction === "inbound"
                        ? "var(--color-surface-subtle)"
                        : "var(--color-brand-light)",
                    color: "var(--color-text-primary)",
                    borderRadius: "var(--radius-card)",
                  }}
                >
                  {message.excerpt || <em style={{ color: "var(--color-text-muted)" }}>No excerpt kept</em>}
                </p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </Modal>
  );
}
