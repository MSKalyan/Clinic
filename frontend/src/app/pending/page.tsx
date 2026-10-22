"use client";

/**
 * Shown after registering without a clinic.
 *
 * The account exists but there is nothing to sign in to yet: the person
 * still has to be added to a clinic by an administrator. Saying that
 * plainly beats showing an empty dashboard.
 */
import Link from "next/link";
import { useEffect } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui";

export default function PendingPage() {
  const { status, clinics, logout } = useAuth();

  // If the user already has a membership (an administrator got there
  // first), there is nothing to wait for.
  useEffect(() => {
    if (status === "authenticated" && clinics.length > 0) {
      window.location.replace("/dashboard");
    }
  }, [status, clinics.length]);

  return (
    <div
      className="flex min-h-screen items-center justify-center px-4 py-12"
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
              backgroundColor: "var(--color-brand-light)",
              color: "var(--color-brand)",
              borderRadius: "var(--radius-card)",
            }}
            aria-hidden="true"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8">
              <circle cx="10" cy="10" r="8" />
              <path d="M10 6v4l2.5 2.5" strokeLinecap="round" />
            </svg>
          </span>

          <h1
            className="mt-5 text-h2"
            style={{ color: "var(--color-text-primary)", letterSpacing: "-0.01em" }}
          >
            Your account is ready
          </h1>
          <p
            className="mt-3 text-body"
            style={{ color: "var(--color-text-secondary)", maxWidth: "46ch" }}
          >
            You still need to be added to a clinic. Ask the clinic administrator to add your
            email address to their staff list — they can do it from the settings page in a
            couple of clicks.
          </p>

          <p
            className="mt-4 text-body-sm"
            style={{ color: "var(--color-text-muted)", maxWidth: "46ch" }}
          >
            If you are setting up a new clinic rather than joining one, sign in and create it
            from the dashboard.
          </p>

          <div className="mt-7 flex flex-wrap gap-3">
            <Link href="/login" className="btn btn-primary">
              Go to sign in
            </Link>
            <Button variant="ghost" onClick={logout}>
              Sign out
            </Button>
          </div>
        </div>

        <p
          className="mt-5 text-center text-caption"
          style={{ color: "var(--color-text-muted)" }}
        >
          <Link href="/" style={{ color: "var(--color-text-secondary)" }}>
            Back to the home page
          </Link>
        </p>
      </div>
    </div>
  );
}
