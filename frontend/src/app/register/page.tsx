"use client";

/**
 * Registration.
 *
 * There are two ways to end up with a usable account, and the page makes
 * you pick one deliberately:
 *
 *   1. **Join a clinic** -- you need an invitation. An administrator adds
 *      your email to their clinic, and you appear in their staff list.
 *   2. **Start a clinic** -- you become its administrator and set it up
 *      yourself.
 *
 * The backend's ``/auth/register/`` creates the person; the clinic is a
 * separate step, because in most deployments a clinic already exists and
 * its administrator is the one who grants access.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button, ErrorBanner, Field, Input, Select } from "@/components/ui";
import type { TokenPair, User } from "@/lib/types";

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

type Mode = "join" | "start";

export default function RegisterPage() {
  const { api, establishSession, refreshClinics, status } = useAuth();
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("join");

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  const [clinicName, setClinicName] = useState("");
  const [clinicSlug, setClinicSlug] = useState("");
  const [timezone, setTimezone] = useState("Asia/Kolkata");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (status === "authenticated") router.replace("/dashboard");
  }, [status, router]);

  // What the web address will actually be, after normalisation.
  const previewSlug = useMemo(
    () => slugify(clinicSlug.trim() || clinicName),
    [clinicSlug, clinicName],
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (password !== confirm) {
      setError(new Error("The two passwords do not match."));
      return;
    }
    if (password.length < 8) {
      setError(new Error("Use at least 8 characters for the password."));
      return;
    }
    if (mode === "start" && !clinicName.trim()) {
      setError(new Error("Give the clinic a name."));
      return;
    }

    setBusy(true);
    try {
      const payload = await api.post<{ user: User; tokens: TokenPair }>("/auth/register/", {
        email: email.trim(),
        password,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        phone: phone.trim(),
      });

      // Install the tokens straight away: creating a clinic needs an
      // authenticated caller.
      await establishSession(payload.tokens, payload.user);

      if (mode === "start") {
        await api.post("/clinics/", {
          name: clinicName.trim(),
          slug: slugify(clinicSlug.trim() || clinicName),
          timezone,
        });
        // The creator is now a clinic admin; pick up the new membership.
        await refreshClinics();
      }

      router.replace(mode === "start" ? "/dashboard" : "/pending");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="flex min-h-screen items-center justify-center px-4 py-12"
      style={{ backgroundColor: "var(--color-surface)" }}
    >
      <div className="w-full" style={{ maxWidth: "32rem" }}>
        <div className="mb-8">
          <Link
            href="/"
            className="inline-flex items-center gap-2"
            style={{ textDecoration: "none" }}
          >
            <span
              className="flex h-7 w-7 items-center justify-center"
              style={{ backgroundColor: "var(--color-brand)", borderRadius: "var(--radius-card)" }}
              aria-hidden="true"
            >
              <svg width="15" height="15" viewBox="0 0 32 32" fill="none">
                <path d="M13 5h6v8h8v6h-8v8h-6v-8H5v-6h8V5z" fill="white" />
              </svg>
            </span>
            <span className="text-body-sm font-medium" style={{ color: "var(--color-text-secondary)" }}>
              Clinic Operations
            </span>
          </Link>

          <h1
            className="mt-6 text-h1"
            style={{ color: "var(--color-text-primary)", letterSpacing: "-0.01em" }}
          >
            Create your account
          </h1>
          <p className="mt-2 text-body" style={{ color: "var(--color-text-secondary)" }}>
            Already have one?{" "}
            <Link href="/login" style={{ color: "var(--color-brand)", fontWeight: 500 }}>
              Sign in
            </Link>
          </p>
        </div>

        {/* Which way in ------------------------------------------------ */}
        <div
          className="mb-6 grid grid-cols-2 gap-2 p-1"
          style={{
            backgroundColor: "var(--color-surface-subtle)",
            borderRadius: "var(--radius-card)",
          }}
        >
          {(
            [
              { value: "join" as const, label: "Join a clinic" },
              { value: "start" as const, label: "Start a clinic" },
            ]
          ).map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setMode(option.value)}
              aria-pressed={mode === option.value}
              className="btn"
              style={{
                height: "2.25rem",
                backgroundColor:
                  mode === option.value ? "var(--color-surface-elevated)" : "transparent",
                color:
                  mode === option.value
                    ? "var(--color-text-primary)"
                    : "var(--color-text-secondary)",
                boxShadow:
                  mode === option.value ? "0 1px 2px 0 rgb(15 23 42 / 0.06)" : "none",
              }}
            >
              {option.label}
            </button>
          ))}
        </div>

        <p
          className="mb-5 text-body-sm"
          style={{ color: "var(--color-text-muted)", maxWidth: "48ch" }}
        >
          {mode === "join"
            ? "Create the account now. A clinic administrator then adds your email address to their staff list and you can sign in."
            : "Create the account and the clinic together. You become the clinic's administrator and can invite your staff straight away."}
        </p>

        <form
          onSubmit={submit}
          className="space-y-5"
          style={{
            backgroundColor: "var(--color-surface-elevated)",
            border: "1px solid var(--color-border-subtle)",
            borderRadius: "var(--radius-card)",
            padding: "var(--space-card)",
          }}
        >
          <div className="grid grid-cols-2 gap-4">
            <Field label="First name">
              <Input
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
                placeholder="Priya"
                autoComplete="given-name"
                disabled={busy}
              />
            </Field>
            <Field label="Last name">
              <Input
                value={lastName}
                onChange={(event) => setLastName(event.target.value)}
                placeholder="Sharma"
                autoComplete="family-name"
                disabled={busy}
              />
            </Field>
          </div>

          <Field label="Email">
            <Input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@clinic.example"
              autoComplete="email"
              disabled={busy}
            />
          </Field>

          <Field label="Phone" hint="Optional. Used to reach you about the clinic.">
            <Input
              type="tel"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="+91 98765 43210"
              autoComplete="tel"
              inputMode="tel"
              disabled={busy}
            />
          </Field>

          <Field label="Password" hint="At least 8 characters.">
            <Input
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              minLength={8}
              disabled={busy}
            />
          </Field>

          <Field label="Confirm password">
            <Input
              type="password"
              required
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              autoComplete="new-password"
              minLength={8}
              disabled={busy}
            />
          </Field>

          {mode === "start" ? (
            <>
              <Field label="Clinic name">
                <Input
                  required
                  value={clinicName}
                  onChange={(event) => setClinicName(event.target.value)}
                  placeholder="Sunrise Family Clinic"
                  disabled={busy}
                />
              </Field>

              <Field
                label="Web address"
                hint="Leave blank to use the clinic name. Spaces and capitals are fine."
              >
                <Input
                  value={clinicSlug}
                  onChange={(event) => setClinicSlug(event.target.value)}
                  placeholder="sunrise-family-clinic"
                  disabled={busy}
                />
              </Field>

              <p className="-mt-2 text-caption" style={{ color: "var(--color-text-muted)" }}>
                Your clinic will live at{" "}
                <span style={{ fontVariantNumeric: "tabular-nums" }}>
                  /{previewSlug}
                </span>
              </p>

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
            </>
          ) : null}

          {error ? <ErrorBanner error={error} /> : null}

          <Button type="submit" variant="primary" disabled={busy} className="w-full">
            {busy
              ? "Creating your account…"
              : mode === "start"
                ? "Create account and clinic"
                : "Create account"}
          </Button>
        </form>
      </div>
    </div>
  );
}

/**
 * Turn anything a person might type into a URL slug.
 *
 * The backend only accepts letters, numbers, underscores and hyphens, so
 * "Sunrise Family Clinic" has to become "sunrise-family-clinic" before it
 * is sent. Normalising here means the user can type a readable address
 * and still get a working link.
 *
 * A name with no ASCII characters at all (a clinic named only in
 * Devanagari, say) would slugify to nothing, so a readable fallback is
 * generated instead of sending an empty value.
 */
function slugify(value: string): string {
  const slug = value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100)
    .replace(/-+$/, "");

  if (slug) return slug;
  return `clinic-${Math.random().toString(36).slice(2, 8)}`;
}
