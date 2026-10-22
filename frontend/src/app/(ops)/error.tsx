"use client";

/**
 * The error boundary for the authenticated shell.
 *
 * Same shape as the root error boundary, but it keeps the sidebar so a
 * user who is mid-task can navigate somewhere else instead of starting
 * again from the home page.
 */
import { useEffect } from "react";

import { Button } from "@/components/ui";

export default function OpsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="page">
      <div style={{ maxWidth: "34rem" }}>
        <span
          className="flex h-10 w-10 items-center justify-center"
          style={{
            backgroundColor: "var(--color-danger-light)",
            color: "var(--color-danger)",
            borderRadius: "var(--radius-card)",
          }}
          aria-hidden="true"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M10 6v5M10 14h.01" strokeLinecap="round" />
            <circle cx="10" cy="10" r="8" />
          </svg>
        </span>

        <h1
          className="mt-5 text-h2"
          style={{ color: "var(--color-text-primary)", letterSpacing: "-0.01em" }}
        >
          This page could not be shown
        </h1>
        <p className="mt-3 text-body" style={{ color: "var(--color-text-secondary)" }}>
          Something failed while rendering. Trying again usually works.
        </p>

        {error.digest ? (
          <p className="mt-4 text-caption" style={{ color: "var(--color-text-muted)" }}>
            Reference: {error.digest}
          </p>
        ) : null}

        <div className="mt-7 flex flex-wrap gap-3">
          <Button variant="primary" onClick={reset}>
            Try again
          </Button>
          <Button variant="secondary" onClick={() => window.location.assign("/dashboard")}>
            Go to the dashboard
          </Button>
        </div>
      </div>
    </div>
  );
}
