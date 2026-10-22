"use client";

/**
 * Small presentational primitives shared by every screen.
 * Updated to use the Clinic design system (globals.css classes).
 */
import type { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes, LabelHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { forwardRef } from "react";

export function Card({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="card-header">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div>{children}</div>
    </section>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
}) {
  const toneClass = {
    neutral: "stat-value-neutral",
    success: "stat-value-success",
    warning: "stat-value-warning",
    danger: "stat-value-danger",
    info: "stat-value-info",
  }[tone];

  return (
    <div className="stat-card">
      <p className="stat-label">{label}</p>
      <p className={`stat-value ${toneClass}`}>{value}</p>
      {hint && <p className="stat-hint">{hint}</p>}
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "info" | "brand";
}) {
  const toneClass = {
    neutral: "badge-neutral",
    success: "badge-success",
    warning: "badge-warning",
    danger: "badge-danger",
    info: "badge-info",
    brand: "badge-brand",
  }[tone];

  return <span className={`badge ${toneClass}`}>{children}</span>;
}

export function StatusBadge({
  status,
  isStale,
}: {
  status: string;
  isStale?: boolean;
}) {
  const tones: Record<string, "success" | "warning" | "danger" | "info" | "neutral" | "brand"> = {
    present: "success",
    running_late: "warning",
    unavailable: "danger",
    on_leave: "danger",
    finished_for_day: "neutral",
    scheduled: "info",
    unknown: "neutral",
    booked: "info",
    confirmed: "success",
    checked_in: "brand",
    completed: "neutral",
    cancelled: "danger",
    no_show: "danger",
    reschedule_pending: "warning",
    open: "info",
    in_progress: "warning",
    resolved: "success",
    declined: "neutral",
    not_required: "neutral",
    low: "neutral",
    normal: "info",
    high: "warning",
    urgent: "danger",
  };

  const labelMap: Record<string, string> = {
    present: "Present",
    running_late: "Running late",
    unavailable: "Unavailable",
    on_leave: "On leave",
    finished_for_day: "Finished",
    scheduled: "Scheduled",
    unknown: "Unknown",
    booked: "Booked",
    confirmed: "Confirmed",
    checked_in: "Checked in",
    completed: "Completed",
    cancelled: "Cancelled",
    no_show: "No show",
    reschedule_pending: "Reschedule",
    open: "Open",
    in_progress: "In progress",
    resolved: "Resolved",
    declined: "Declined",
    not_required: "Not required",
    low: "Low",
    normal: "Normal",
    high: "High",
    urgent: "Urgent",
  };

  const tone = tones[status] ?? "neutral";
  const label = labelMap[status] ?? status;

  return (
    <span className="flex items-center gap-1.5">
      <Badge tone={tone}>{label}</Badge>
      {isStale && <Badge tone="warning">Stale</Badge>}
    </span>
  );
}

export function Table({
  headers,
  children,
  empty = "Nothing to show.",
  dense = true,
}: {
  headers: string[];
  children: ReactNode;
  empty?: string;
  dense?: boolean;
}) {
  const rows = Array.isArray(children) ? children.filter(Boolean) : children;
  const isEmpty = Array.isArray(rows) ? rows.length === 0 : !rows;

  return (
    <div className="table-wrapper">
      <table className={`table ${dense ? "table-dense" : ""}`}>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200">
          {isEmpty ? (
            <tr>
              <td colSpan={headers.length} className="table-empty">
                {empty}
              </td>
            </tr>
          ) : (
            rows
          )}
        </tbody>
      </table>
    </div>
  );
}

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof Error ? error.message : "Something went wrong. Please try again.";
  return (
    <div className="error-banner" role="alert">
      {message}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <p className="empty-state-title">{title}</p>
      {hint && <p className="empty-state-hint">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading…", size = "md" }: { label?: string; size?: "sm" | "md" | "lg" }) {
  const sizeClass = {
    sm: "w-4 h-4",
    md: "w-6 h-6",
    lg: "w-8 h-8",
  }[size];

  return (
    <div className="flex items-center gap-2 py-6 text-sm text-slate-500">
      <span className={`spinner ${sizeClass}`} aria-hidden="true" />
      {label}
    </div>
  );
}

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "secondary" | "ghost" | "danger";
    size?: "sm" | "md";
  }
>(({ children, variant = "secondary", size = "md", disabled, className = "", ...props }, ref) => {
  const variantClass = {
    primary: "btn-primary",
    secondary: "btn-secondary",
    ghost: "btn-ghost",
    danger: "btn-danger",
  }[variant];

  const sizeClass = size === "sm" ? "btn-sm" : "";

  return (
    <button
      ref={ref}
      disabled={disabled}
      className={`btn ${variantClass} ${sizeClass} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
});
Button.displayName = "Button";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className = "", ...props }, ref) => (
    <input ref={ref} className={`input ${className}`} {...props} />
  )
);
Input.displayName = "Input";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className = "", ...props }, ref) => (
    <select ref={ref} className={`input ${className}`} {...props} />
  )
);
Select.displayName = "Select";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className = "", ...props }, ref) => (
    <textarea ref={ref} className={`input ${className} resize-y min-h-[80px]`} {...props} />
  )
);
Textarea.displayName = "Textarea";

export const Label = forwardRef<HTMLLabelElement, LabelHTMLAttributes<HTMLLabelElement>>(
  ({ children, className = "", ...props }, ref) => (
    <label ref={ref} className={`label ${className}`} {...props}>
      {children}
    </label>
  )
);
Label.displayName = "Label";

export function Field({
  label,
  children,
  hint,
  error,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
  error?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
      {error ? (
        <p className="text-caption" style={{ color: "var(--color-danger)" }}>{error}</p>
      ) : hint ? (
        <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>{hint}</p>
      ) : null}
    </div>
  );
}

export function Modal({
  isOpen,
  onClose,
  title,
  children,
  action,
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  if (!isOpen) return null;

  return (
    <>
      <div className="modal-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div className="p-6 border-b border-slate-200 flex items-start justify-between gap-4">
          <h2 id="modal-title" className="card-title">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost p-1.5 rounded-lg"
            aria-label="Close"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M15 5L5 15M5 5L15 15" />
            </svg>
          </button>
        </div>
        <div className="p-6">{children}</div>
        {action && (
          <div className="p-6 border-t border-slate-200 flex justify-end gap-3">
            {action}
          </div>
        )}
      </div>
    </>
  );
}

export function Toast({
  message,
  tone = "info",
  onClose,
}: {
  message: string;
  tone?: "success" | "warning" | "danger" | "info";
  onClose: () => void;
}) {
  const toneClass = {
    success: "toast-success",
    warning: "toast-warning",
    danger: "toast-danger",
    info: "toast-info",
  }[tone];

  return (
    <div className={`toast ${toneClass}`} role="alert">
      <div className="flex-1 text-sm">{message}</div>
      <button
        type="button"
        onClick={onClose}
        className="btn-ghost p-1 rounded-lg text-muted"
        aria-label="Dismiss"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M11 5L5 11M5 5L11 11" />
        </svg>
      </button>
    </div>
  );
}