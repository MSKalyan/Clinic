"use client";

/**
 * Conversations — live patient messaging.
 *
 * The list and the open thread are both kept up to date over the clinic
 * WebSocket. New inbound messages appear instantly; staff replies appear in
 * the thread as soon as the worker records them. There is no polling.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Input,
  Modal,
  Select,
  Spinner,
  Table,
} from "@/components/ui";
import { formatDateTime, humanise } from "@/lib/format";
import type { Conversation, ConversationMessage, Paginated } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";
import { useClinicSocket } from "@/lib/use-clinic-socket";

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
  { value: "taken_over", label: "Taken over" },
  { value: "completed", label: "Completed" },
  { value: "abandoned", label: "Abandoned" },
];

const STATUS_TONE: Record<string, "info" | "warning" | "neutral" | "success"> = {
  open: "info",
  escalated: "warning",
  taken_over: "warning",
  completed: "success",
  abandoned: "neutral",
};

export default function ConversationsPage() {
  const { activeClinic, activeClinicId } = useAuth();
  const timezone = activeClinic?.timezone;

  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, error, loading, refreshing, reload } = useApiData<{
    conversations: Paginated<Conversation>;
  }>(
    async (api, signal) => {
      const params: Record<string, string> = {};
      if (channel) params.channel = channel;
      if (status) params.status = status;
      const conversations = await api.get<Paginated<Conversation>>("/conversations/", {
        params,
        signal,
      });
      return { conversations };
    },
    `${channel}:${status}`,
  );

  const rows = useMemo(() => data?.conversations.results ?? [], [data]);

  const onEvent = useCallback(
    (event: { event: string; data: Record<string, unknown> }) => {
      if (event.event === "conversation.message" || event.event === "conversation.new") {
        // Re-fetch the list: cheap and keeps counts/sorting correct.
        reload();
      }
      if (event.event === "conversation.message" || event.event === "conversation.updated") {
        const conversationId = String(event.data.conversation_id ?? "");
        if (conversationId) {
          // The detail component handles the thread update via its own socket.
          void conversationId;
        }
      }
    },
    [reload],
  );

  const { connected } = useClinicSocket(onEvent);

  const selected = useMemo(
    () => rows.find((row) => row.id === selectedId) ?? null,
    [rows, selectedId],
  );

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Conversations</h1>
          <p className="page-subtitle">
            {data?.conversations.count ?? 0} interaction
            {data?.conversations.count === 1 ? "" : "s"} across every channel.
            <span className="ml-2 inline-flex items-center gap-1 text-caption">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: connected ? "var(--color-success)" : "var(--color-text-muted)" }}
                aria-hidden
              />
              {connected ? "Live" : "Connecting…"}
            </span>
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
        </div>
      </header>

      {error ? <ErrorBanner error={error} /> : null}
      {refreshing ? (
        <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
          Refreshing…
        </p>
      ) : null}

      <Card
        title="Interactions"
        subtitle="Newest first. Open one to read and reply to the live thread."
      >
        {loading && rows.length === 0 ? (
          <Spinner label="Loading conversations…" />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No conversations match this view"
            hint="Calls, WhatsApp messages and texts appear here as patients get in touch."
          />
        ) : (
          <Table
            headers={["Started", "Patient", "Channel", "Status", "Summary", ""]}
            empty="No conversations."
          >
            {rows.map((conversation) => (
              <tr key={conversation.id}>
                <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                  {formatDateTime(conversation.started_at ?? conversation.created_at, timezone)}
                </td>
                <td className="px-4 py-3">
                  <p className="font-medium" style={{ color: "var(--color-text-primary)" }}>
                    {conversation.patient_name || "Unknown patient"}
                  </p>
                  <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
                    {conversation.patient_phone || "No phone on file"}
                  </p>
                </td>
                <td className="px-4 py-3">
                  <Badge tone={conversation.channel === "whatsapp" ? "success" : "neutral"}>
                    {humanise(conversation.channel)}
                  </Badge>
                </td>
                <td className="px-4 py-3">
                  <Badge tone={STATUS_TONE[conversation.status] ?? "neutral"}>
                    {humanise(conversation.status)}
                  </Badge>
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
                  <Button variant="ghost" onClick={() => setSelectedId(conversation.id)}>
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
          onClose={() => setSelectedId(null)}
          onListRefresh={reload}
        />
      ) : null}
    </div>
  );
}

function ConversationDetail({
  conversation,
  timezone,
  onClose,
  onListRefresh,
}: {
  conversation: Conversation;
  timezone: string | undefined;
  onClose: () => void;
  onListRefresh: () => void;
}) {
  const { api } = useAuth();
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<unknown>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(true);
  const messagesRef = useRef<ConversationMessage[]>([]);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const { subscribe, unsubscribe } = useClinicSocket((event) => {
    if (event.event === "conversation.message" || event.event === "conversation.reply") {
      const incoming = event.data.message as ConversationMessage | undefined;
      if (!incoming) return;
      setMessages((current) => {
        if (current.some((message) => message.id === incoming.id)) return current;
        return [...current, incoming].sort((a, b) => a.created_at.localeCompare(b.created_at));
      });
    }
  });

  useEffect(() => {
    subscribe(conversation.id);
    return () => unsubscribe(conversation.id);
  }, [conversation.id, subscribe, unsubscribe]);

  useEffect(() => {
    let disposed = false;
    setLoadingMessages(true);
    api
      .get<{ conversation: Conversation; messages: ConversationMessage[] }>(
        `/conversations/${conversation.id}/`,
      )
      .then((payload) => {
        if (disposed) return;
        const sorted = [...payload.messages].sort((a, b) =>
          a.created_at.localeCompare(b.created_at),
        );
        messagesRef.current = sorted;
        setMessages(sorted);
      })
      .catch((cause) => setSendError(cause))
      .finally(() => {
        if (!disposed) setLoadingMessages(false);
      });
    return () => {
      disposed = true;
    };
  }, [api, conversation.id]);

  useEffect(() => {
    messagesRef.current = messages;
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function sendReply() {
    const text = reply.trim();
    if (!text) return;
    setSending(true);
    setSendError(null);
    // Optimistic local bubble; the socket confirms with the real record.
    const optimisticId = `pending-${Date.now()}`;
    setMessages((current) => [
      ...current,
      {
        id: optimisticId,
        direction: "outbound",
        message_type: "text",
        excerpt: text,
        created_at: new Date().toISOString(),
      },
    ]);
    try {
      await api.post("/integrations/waha/messages/", {
        conversation_id: conversation.id,
        text,
      });
      setReply("");
      onListRefresh();
    } catch (cause) {
      setSendError(cause);
      setMessages((current) => current.filter((message) => message.id !== optimisticId));
    } finally {
      setSending(false);
    }
  }

  const canReply = conversation.channel === "whatsapp" && !!conversation.provider_conversation_id;

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`${humanise(conversation.channel)} with ${conversation.patient_name || "patient"}`}
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
          <span className="text-caption" style={{ color: "var(--color-text-muted)" }}>
            {formatDateTime(conversation.started_at ?? conversation.created_at, timezone)}
          </span>
        </div>

        <p className="text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
          {conversation.patient_name || "Unknown patient"}
          {conversation.patient_phone ? ` · ${conversation.patient_phone}` : ""}
        </p>

        {loadingMessages ? (
          <Spinner label="Loading the conversation…" />
        ) : messages.length === 0 ? (
          <EmptyState
            title="No messages yet"
            hint="Messages in this conversation will appear here as they arrive."
          />
        ) : (
          <ol className="space-y-3">
            {messages.map((message) => {
              const outgoing = message.direction === "outbound";
              const pending = message.id.startsWith("pending-");
              return (
                <li key={message.id} className={outgoing ? "text-right" : "text-left"}>
                  <div
                    className="mb-1 flex items-center gap-2"
                    style={{ justifyContent: outgoing ? "flex-end" : "flex-start" }}
                  >
                    <span className="text-caption" style={{ color: "var(--color-text-muted)" }}>
                      {outgoing ? "You" : conversation.patient_name || "Patient"} ·{" "}
                      {formatDateTime(message.created_at, timezone)}
                      {pending ? " · sending…" : ""}
                    </span>
                  </div>
                  <p
                    className="inline-block px-3 py-2 text-body-sm text-left"
                    style={{
                      backgroundColor: outgoing
                        ? "var(--color-brand-light)"
                        : "var(--color-surface-subtle)",
                      color: "var(--color-text-primary)",
                      borderRadius: "var(--radius-card)",
                      maxWidth: "85%",
                      opacity: pending ? 0.6 : 1,
                    }}
                  >
                    {message.excerpt || <em style={{ color: "var(--color-text-muted)" }}>No excerpt kept</em>}
                  </p>
                </li>
              );
            })}
            <div ref={bottomRef} />
          </ol>
        )}

        {canReply ? (
          <div className="space-y-2 border-t pt-4" style={{ borderColor: "var(--color-border-subtle)" }}>
            {sendError ? <ErrorBanner error={sendError} /> : null}
            <Input
              value={reply}
              onChange={(event) => setReply(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendReply();
                }
              }}
              placeholder="Reply to this patient on WhatsApp…"
              aria-label="WhatsApp reply"
              disabled={sending}
            />
            <div className="flex justify-end">
              <Button variant="primary" onClick={sendReply} disabled={sending || !reply.trim()}>
                {sending ? "Sending…" : "Send reply"}
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
