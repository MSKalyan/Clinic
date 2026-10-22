"use client";

/**
 * What a signed-in user sees when they belong to no clinic.
 *
 * This used to be a dead end: a paragraph asking them to find an
 * administrator. The two ways a person can end up here are both
 * recoverable, so the screen offers both.
 *
 *   * They have not been added to a clinic yet -- they have to wait for an
 *     administrator. Nothing to do but check back.
 *   * They are setting up a new clinic -- they can create one now and
 *     become its administrator.
 */
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button, ErrorBanner, Field, Input, Select } from "@/components/ui";

const TIMEZONES = [
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Dubai",
  "Asia/Karachi",
  "Asia/Dhaka",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Los_Angeles",
  "Australia/Sydney",
];

export function NoClinic() {
  const { api, refreshClinics, user } = useAuth();

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [showForm, setShowForm] = useState(false);

  async function createClinic() {
    if (!name.trim()) {
      setError(new Error("Give the clinic a name."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post("/clinics/", {
        name: name.trim(),
        slug: slugify(slug.trim() || name),
        timezone,
      });
      // The creator is now a clinic admin. Re-read the memberships so the
      // session picks the new clinic up.
      await refreshClinics();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="w-full" style={{ maxWidth: "32rem" }}>
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
            <path d="M3 10h14M10 3v14" strokeLinecap="round" />
          </svg>
        </span>

        <h1
          className="mt-5 text-h2"
          style={{ color: "var(--color-text-primary)", letterSpacing: "-0.01em" }}
        >
          You are not in a clinic yet
        </h1>
        <p
          className="mt-3 text-body"
          style={{ color: "var(--color-text-secondary)", maxWidth: "48ch" }}
        >
          Everything in this dashboard belongs to a clinic, so there is nothing to show until
          you are a member of one.
        </p>

        {user?.email ? (
          <p className="mt-4 text-body-sm" style={{ color: "var(--color-text-muted)" }}>
            Signed in as {user.email}
          </p>
        ) : null}

        <div
          className="mt-6 space-y-3 rounded-lg p-4"
          style={{ backgroundColor: "var(--color-surface-subtle)" }}
        >
          <p className="text-body-sm font-medium" style={{ color: "var(--color-text-primary)" }}>
            Joining a clinic you already work at
          </p>
          <p className="text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
            A clinic administrator adds your email address to their staff list. You will find
            the clinic here the moment they do -- refresh this page.
          </p>
        </div>

        {showForm ? (
          <div className="mt-6 space-y-4">
            <Field label="Clinic name">
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Sunrise Family Clinic"
                autoFocus
                disabled={busy}
              />
            </Field>
            <Field
              label="Web address"
              hint="Leave blank to use the clinic name. Spaces and capitals are fine."
            >
              <Input
                value={slug}
                onChange={(event) => setSlug(event.target.value)}
                placeholder="sunrise-family-clinic"
                disabled={busy}
              />
            </Field>
            <Field label="Timezone" hint="Every appointment time is shown in this zone.">
              <Select
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
                disabled={busy}
              >
                {TIMEZONES.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone}
                  </option>
                ))}
              </Select>
            </Field>

            {error ? <ErrorBanner error={error} /> : null}

            <div className="flex flex-wrap gap-3">
              <Button variant="primary" onClick={createClinic} disabled={busy}>
                {busy ? "Creating…" : "Create clinic"}
              </Button>
              <Button variant="ghost" onClick={() => setShowForm(false)} disabled={busy}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-6">
            <p className="text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
              Setting up a new clinic? Create it and you will become its administrator.
            </p>
            <Button variant="primary" onClick={() => setShowForm(true)} className="mt-3">
              Create a clinic
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Turn anything a person might type into a URL slug.
 *
 * The backend only accepts letters, numbers, underscores and hyphens, so
 * "Sunrise Family Clinic" has to become "sunrise-family-clinic" before it
 * is sent. A name with no ASCII characters at all would slugify to
 * nothing, so a readable fallback is generated instead.
 */
function slugify(value: string): string {
  const slug = value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+/, "")
    .replace(/-+$/, "")
    .slice(0, 100)
    .replace(/-+$/, "");

  if (slug) return slug;
  return `clinic-${Math.random().toString(36).slice(2, 8)}`;
}
