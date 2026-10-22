"use client";

/**
 * The error boundary for a route segment.
 *
 * Next.js renders this instead of the page when a render throws. The
 * dashboard talks to the API on the client, so most failures are caught
 * by the screens themselves -- this is the last line of defence.
 */
import { useEffect } from "react";

import { Button } from "@/components/ui";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // In production this is where the error would go to Sentry.
    console.error(error);
  }, [error]);

  return (
    <div
      className="flex min-h-screen items-center justify-center px-4"
      style={{ backgroundColor: "var(--color-surface)" }}
    >
      <div className="w-full" style={{ maxWidth: "30rem" }}>
        <div
          style={{
            backgroundColor: "var(--color-surface-elevated)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: "var(--radius-card)",
            padding: "var(--space-card)",
          }}
        >
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
            Something went wrong
          </h1>
          <p
            className="mt-3 text-body"
            style={{ color: "var(--color-text-secondary)", maxWidth: "46ch" }}
          >
            The page could not be shown. Trying again usually works. If it keeps happening, tell
            the clinic administrator — the reference below identifies the failure in the logs.
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
    </div>
  );
}
