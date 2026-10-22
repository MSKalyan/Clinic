"use client";

/**
 * The follow-up queue.
 *
 * Every task here is work the assistant could not finish alone. The screen
 * is built around one action: pick a task, do it, close it. Everything else
 * is there to help you decide which task to pick.
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
import { formatDateTime, formatTime, humanise } from "@/lib/format";
import type { FollowUpTask, Paginated } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

const STATUS_OPTIONS = [
  { value: "open,in_progress", label: "Active" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "resolved", label: "Resolved" },
  { value: "declined,not_required", label: "Closed without action" },
  { value: "", label: "All" },
];

const PRIORITY_OPTIONS = [
  { value: "", label: "Any priority" },
  { value: "urgent", label: "Urgent" },
  { value: "high", label: "High" },
  { value: "normal", label: "Normal" },
  { value: "low", label: "Low" },
];

const PRIORITIES = ["low", "normal", "high", "urgent"];

const TASK_TYPE_LABELS: Record<string, string> = {
  booking_request: "Book an appointment",
  reschedule_request: "Reschedule an appointment",
  clinical_question: "Clinical question",
  prescription_refill: "Prescription refill",
  callback_request: "Call the patient back",
  complaint: "Complaint",
  insurance_verification: "Insurance verification",
  other: "Other",
};

function TaskModal({
  task,
  onClose,
  onDone,
}: {
  task: FollowUpTask | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const { api } = useAuth();
  const [status, setStatus] = useState("in_progress");
  const [priority, setPriority] = useState("normal");
  const [notes, setNotes] = useState("");
  const [resolution, setResolution] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function save() {
    if (!task) return;
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/follow-ups/${task.id}/`, {
        status,
        priority,
        notes,
      });
      if (status === "resolved") {
        await api.post(`/follow-ups/${task.id}/resolve/`, {
          resolution_reason: resolution,
          notes,
        });
      }
      onDone();
      onClose();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (!task) return null;

  return (
    <Modal
      isOpen={Boolean(task)}
      onClose={onClose}
      title={TASK_TYPE_LABELS[task.task_type] ?? humanise(task.task_type)}
      action={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save changes"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {error ? <ErrorBanner error={error} /> : null}

        <div className="text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
          {task.patient_name || "No patient linked"} ·{" "}
          {task.due_at ? `due ${formatDateTime(task.due_at)}` : "no due time"}
        </div>

        {task.notes ? (
          <div
            className="px-3 py-2 text-body-sm"
            style={{
              backgroundColor: "var(--color-surface-subtle)",
              borderRadius: "var(--radius-card)",
              color: "var(--color-text-secondary)",
            }}
          >
            {task.notes}
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-4">
          <Field label="Status">
            <Select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="open">Open</option>
              <option value="in_progress">In progress</option>
              <option value="resolved">Resolved</option>
              <option value="declined">Declined</option>
              <option value="not_required">Not required</option>
            </Select>
          </Field>
          <Field label="Priority">
            <Select value={priority} onChange={(event) => setPriority(event.target.value)}>
              {PRIORITIES.map((value) => (
                <option key={value} value={value}>
                  {humanise(value)}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {status === "resolved" ? (
          <Field label="Resolution" hint="Kept with the task so the next person knows what happened.">
            <Input
              value={resolution}
              onChange={(event) => setResolution(event.target.value)}
              placeholder="Appointment booked for Thursday"
            />
          </Field>
        ) : null}

        <Field label="Notes">
          <Textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Called the patient, left a message"
            rows={3}
          />
        </Field>
      </div>
    </Modal>
  );
}

export default function FollowUpsPage() {
  const { api, activeClinic, activeClinicId } = useAuth();
  const timezone = activeClinic?.timezone;

  const [status, setStatus] = useState("open,in_progress");
  const [priority, setPriority] = useState("");
  const [selected, setSelected] = useState<FollowUpTask | null>(null);
  const [quickStatus, setQuickStatus] = useState<Record<string, string>>({});

  const { data, error, loading, reload } = useApiData<{ tasks: Paginated<FollowUpTask> }>(
    async (api, signal) => {
      const params: Record<string, string> = {};
      if (status) params.status = status;
      if (priority) params.priority = priority;
      const tasks = await api.get<Paginated<FollowUpTask>>("/follow-ups/", {
        params,
        signal,
      });
      return { tasks };
    },
    `${activeClinicId ?? ""}:${status}:${priority}`,
  );

  const rows = useMemo(() => {
    const list = data?.tasks.results ?? [];
    return [...list].sort((a, b) => {
      const priorityOrder = PRIORITIES.indexOf(b.priority) - PRIORITIES.indexOf(a.priority);
      if (priorityOrder !== 0) return priorityOrder;
      if (!a.due_at) return 1;
      if (!b.due_at) return -1;
      return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
    });
  }, [data]);

  async function setTaskStatus(task: FollowUpTask, next: string) {
    setQuickStatus((current) => ({ ...current, [task.id]: next }));
    try {
      await api.patch(`/follow-ups/${task.id}/`, { status: next });
      reload();
    } catch (cause) {
      setActionError(cause);
    } finally {
      setQuickStatus((current) => {
        const copy = { ...current };
        delete copy[task.id];
        return copy;
      });
    }
  }

  const [actionError, setActionError] = useState<unknown>(null);

  if (loading) return <Spinner label="Loading the queue…" size="lg" />;
  if (error) return <ErrorBanner error={error} />;

  const overdue = rows.filter(
    (task) =>
      task.due_at &&
      ["open", "in_progress"].includes(task.status) &&
      new Date(task.due_at).getTime() < Date.now(),
  ).length;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Follow-ups</h1>
          <p className="page-subtitle">
            {rows.length} task{rows.length === 1 ? "" : "s"} in this view
            {overdue > 0 ? ` · ${overdue} overdue` : ""}.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            aria-label="Filter by status"
            style={{ width: "12rem" }}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
          <Select
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
            aria-label="Filter by priority"
            style={{ width: "10rem" }}
          >
            {PRIORITY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </div>
      </header>

      {actionError ? (
        <div style={{ marginBottom: "var(--space-section)" }}>
          <ErrorBanner error={actionError} />
        </div>
      ) : null}

      <Card
        title="Queue"
        subtitle="Sorted by priority, then by due time. The oldest request stays at the top."
      >
        {rows.length === 0 ? (
          <EmptyState
            title="The queue is clear"
            hint="Nothing needs a person right now. New tasks appear here as the assistant escalates."
          />
        ) : (
          <Table headers={["Task", "Patient", "Priority", "Due", "Status", ""]} empty="Queue is clear.">
            {rows.map((task) => {
              const isOverdue =
                task.due_at &&
                ["open", "in_progress"].includes(task.status) &&
                new Date(task.due_at).getTime() < Date.now();
              return (
                <tr key={task.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium" style={{ color: "var(--color-text-primary)" }}>
                      {TASK_TYPE_LABELS[task.task_type] ?? humanise(task.task_type)}
                    </p>
                    {task.notes ? (
                      <p
                        className="text-caption"
                        style={{
                          color: "var(--color-text-muted)",
                          maxWidth: "22rem",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {task.notes}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--color-text-secondary)" }}>
                    {task.patient_name || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={task.priority} />
                  </td>
                  <td
                    className="px-4 py-3"
                    style={{ color: isOverdue ? "var(--color-danger)" : "var(--color-text-secondary)" }}
                  >
                    {task.due_at ? formatTime(task.due_at, timezone) : "—"}
                    {isOverdue ? (
                      <span className="ml-1 text-caption">overdue</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={task.status} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      {task.status === "open" ? (
                        <Button
                          variant="ghost"
                          onClick={() => setTaskStatus(task, "in_progress")}
                          disabled={quickStatus[task.id] !== undefined}
                        >
                          Start
                        </Button>
                      ) : null}
                      {["open", "in_progress"].includes(task.status) ? (
                        <Button
                          variant="ghost"
                          onClick={() => setTaskStatus(task, "resolved")}
                          disabled={quickStatus[task.id] !== undefined}
                        >
                          Resolve
                        </Button>
                      ) : null}
                      <Button variant="ghost" onClick={() => setSelected(task)}>
                        Open
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>

      <TaskModal task={selected} onClose={() => setSelected(null)} onDone={reload} />
    </div>
  );
}