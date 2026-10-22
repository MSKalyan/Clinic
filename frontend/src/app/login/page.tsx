"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button, ErrorBanner, Field, Input } from "@/components/ui";

export default function LoginPage() {
  const { login, status } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (status === "authenticated") router.replace("/dashboard");
  }, [status, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      router.replace("/dashboard");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="flex min-h-screen items-center justify-center px-4"
      style={{ backgroundColor: "var(--color-surface)" }}
    >
      <div className="w-full" style={{ maxWidth: "24rem" }}>
        <div className="mb-8">
          <Link href="/" className="inline-flex items-center gap-2" style={{ textDecoration: "none" }}>
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
            Sign in
          </h1>
          <p className="mt-2 text-body" style={{ color: "var(--color-text-secondary)" }}>
            Use the email address your clinic administrator invited.
          </p>
        </div>

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
          <Field label="Email">
            <Input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@clinic.example"
              disabled={busy}
            />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="••••••••"
              disabled={busy}
            />
          </Field>

          {error ? <ErrorBanner error={error} /> : null}

          <Button type="submit" variant="primary" disabled={busy} className="w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        <p className="mt-6 text-center text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
          No account yet?{" "}
          <Link href="/register" style={{ color: "var(--color-brand)", fontWeight: 500 }}>
            Create one
          </Link>
        </p>

        <p
          className="mt-4 text-center text-caption"
          style={{ color: "var(--color-text-muted)" }}
        >
          Sessions are tenant-scoped. The clinic is chosen from your membership after sign-in.
        </p>
      </div>
    </div>
  );
}
