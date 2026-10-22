"use client";

/**
 * The call-to-action on the landing page.
 *
 * The session lives in ``localStorage``, so only the browser knows whether
 * somebody is already signed in. This small client component is what
 * adapts the buttons; the rest of the landing page stays a server
 * component and costs nothing to deliver.
 */
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";

export function LandingCta({ size = "md" }: { size?: "md" | "lg" }) {
  const { status } = useAuth();

  if (status === "authenticated") {
    return (
      <Link href="/dashboard" className={`btn btn-primary ${size === "lg" ? "h-12 px-5" : ""}`}>
        Open the dashboard
      </Link>
    );
  }

  if (status === "loading") {
    return (
      <span
        className="inline-flex h-10 items-center rounded-lg px-4 text-body-sm"
        style={{ color: "var(--color-text-muted)" }}
      >
        Checking your session…
      </span>
    );
  }

  return (
    <>
      <Link href="/register" className={`btn btn-primary ${size === "lg" ? "h-12 px-5" : ""}`}>
        Create an account
      </Link>
      <Link href="/login" className={`btn btn-secondary ${size === "lg" ? "h-12 px-5" : ""}`}>
        I already have one
      </Link>
    </>
  );
}
