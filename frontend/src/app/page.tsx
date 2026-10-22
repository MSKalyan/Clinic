import type { Metadata } from "next";
import Link from "next/link";

import { LandingCta } from "@/components/landing-cta";

export const metadata: Metadata = {
  title: "Clinic Operations — the assistant that answers your phone",
  description:
    "An AI assistant for clinics: it answers calls, books appointments, sends reminders and escalates what it cannot finish, while the dashboard shows you exactly where things stand.",
};

const CAPABILITIES = [
  {
    title: "It answers the phone",
    body: "Patients call, message on WhatsApp or text. The assistant greets them in their language, checks the live rota, and books the slot that is actually free.",
  },
  {
    title: "It never guesses",
    body: "A rota entry is a schedule, not a confirmation. Presence is an explicit assertion recorded with an author and a timestamp, so 'the doctor is late' is never inferred from a spreadsheet.",
  },
  {
    title: "It escalates honestly",
    body: "When the assistant cannot finish something safely — a clinical question, a complaint, an emergency keyword — it stops and puts a human task in the queue with a priority and a due time.",
  },
  {
    title: "It respects the patient",
    body: "Consent is captured per channel. A patient who opts out of WhatsApp is never messaged on WhatsApp, and the preference is on the record where staff can see it.",
  },
];

const SCREEN = [
  { label: "Appointments today", value: "24", width: "68%" },
  { label: "Doctors present", value: "6 / 8", width: "75%" },
  { label: "Open follow-ups", value: "8", width: "42%" },
  { label: "Overdue tasks", value: "2", width: "22%" },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen" style={{ backgroundColor: "var(--color-surface)" }}>
      <header
        className="flex flex-wrap items-center justify-between gap-4 px-6 py-4"
        style={{
          backgroundColor: "var(--color-surface-elevated)",
          borderBottom: "1px solid var(--color-border-subtle)",
        }}
      >
        <Link href="/" className="flex items-center gap-2.5" style={{ textDecoration: "none" }}>
          <span
            className="flex h-8 w-8 items-center justify-center"
            style={{ backgroundColor: "var(--color-brand)", borderRadius: "var(--radius-card)" }}
            aria-hidden="true"
          >
            <svg width="18" height="18" viewBox="0 0 32 32" fill="none">
              <path
                d="M13 5h6v8h8v6h-8v8h-6v-8H5v-6h8V5z"
                fill="white"
              />
            </svg>
          </span>
          <span
            className="text-body font-semibold"
            style={{ color: "var(--color-text-primary)", letterSpacing: "-0.01em" }}
          >
            Clinic Operations
          </span>
        </Link>

        <nav className="flex items-center gap-2">
          <LandingCta />
        </nav>
      </header>

      <main>
        {/* Hero ------------------------------------------------------- */}
        <section
          className="grid gap-12 px-6 py-20 lg:grid-cols-[1.1fr_0.9fr] lg:items-center lg:py-28"
          style={{ maxWidth: "1200px", margin: "0 auto" }}
        >
          <div>
            <h1
              className="text-balance"
              style={{
                fontSize: "clamp(2.5rem, 5vw, 3.75rem)",
                fontWeight: 600,
                lineHeight: 1.1,
                letterSpacing: "-0.025em",
                color: "var(--color-text-primary)",
              }}
            >
              Your receptionist never sleeps, and never guesses.
            </h1>
            <p
              className="mt-6 text-body-lg"
              style={{
                color: "var(--color-text-secondary)",
                maxWidth: "56ch",
                lineHeight: 1.6,
              }}
            >
              An assistant for clinics that answers calls and messages, books real appointments,
              chases reminders — and hands you a clear queue of everything it could not finish
              on its own.
            </p>

            <div className="mt-9 flex flex-wrap items-center gap-3">
              <LandingCta size="lg" />
            </div>

            <p
              className="mt-6 text-caption"
              style={{ color: "var(--color-text-muted)", maxWidth: "52ch" }}
            >
              Every clinic lives in its own tenant. A member of one clinic can never read
              another clinic&apos;s patients, bookings or call records.
            </p>
          </div>

          {/* The product, shown rather than described -------------------- */}
          <div
            style={{
              backgroundColor: "var(--color-surface-elevated)",
              border: "1px solid var(--color-border-subtle)",
              borderRadius: "var(--radius-card)",
              overflow: "hidden",
            }}
          >
            <div
              className="flex items-center justify-between px-5 py-3"
              style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
            >
              <span className="text-body-sm font-medium" style={{ color: "var(--color-text-primary)" }}>
                Today
              </span>
              <span className="text-caption" style={{ color: "var(--color-text-muted)" }}>
                Sunrise Family Clinic · Asia/Kolkata
              </span>
            </div>

            <div className="space-y-4 p-5">
              {SCREEN.map((row) => (
                <div key={row.label}>
                  <div className="mb-1.5 flex items-baseline justify-between gap-3">
                    <span className="text-body-sm" style={{ color: "var(--color-text-secondary)" }}>
                      {row.label}
                    </span>
                    <span
                      className="font-semibold"
                      style={{
                        color: "var(--color-text-primary)",
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {row.value}
                    </span>
                  </div>
                  <div
                    style={{
                      height: "6px",
                      backgroundColor: "var(--color-surface-subtle)",
                      borderRadius: "9999px",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        width: row.width,
                        height: "100%",
                        backgroundColor:
                          row.label === "Overdue tasks" ? "var(--color-danger)" : "var(--color-brand)",
                        borderRadius: "9999px",
                      }}
                    />
                  </div>
                </div>
              ))}

              <div
                className="mt-6 rounded-lg px-4 py-3"
                style={{ backgroundColor: "var(--color-warning-light)" }}
              >
                <p className="text-body-sm font-medium" style={{ color: "var(--color-warning)" }}>
                  Dr. Iyer is running late
                </p>
                <p className="mt-0.5 text-caption" style={{ color: "var(--color-warning)" }}>
                  Recorded from the dashboard, 09:12 · 4 patients affected
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Capabilities ---------------------------------------------- */}
        <section
          style={{
            backgroundColor: "var(--color-surface-elevated)",
            borderTop: "1px solid var(--color-border-subtle)",
            borderBottom: "1px solid var(--color-border-subtle)",
          }}
        >
          <div className="px-6 py-20" style={{ maxWidth: "1200px", margin: "0 auto" }}>
            <h2
              className="text-h1"
              style={{ color: "var(--color-text-primary)", maxWidth: "20ch" }}
            >
              Built for clinics, not for demos
            </h2>

            <div className="mt-12 grid gap-10 sm:grid-cols-2">
              {CAPABILITIES.map((item) => (
                <div key={item.title}>
                  <h3 className="text-h3" style={{ color: "var(--color-text-primary)" }}>
                    {item.title}
                  </h3>
                  <p
                    className="mt-2 text-body"
                    style={{ color: "var(--color-text-secondary)", maxWidth: "52ch" }}
                  >
                    {item.body}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* How it works ----------------------------------------------- */}
        <section className="px-6 py-20" style={{ maxWidth: "1200px", margin: "0 auto" }}>
          <h2 className="text-h1" style={{ color: "var(--color-text-primary)" }}>
            How a call goes
          </h2>

          <ol className="mt-12 space-y-8">
            {[
              {
                step: "The patient calls",
                body: "The assistant picks up in the language the patient prefers, and identifies them by phone number.",
              },
              {
                step: "It checks the real rota",
                body: "Availability comes from the doctor's schedule, their exceptions, their current status and every existing booking — not from a guess.",
              },
              {
                step: "It books, or it escalates",
                body: "A free slot is booked and a reminder is scheduled. A clinical question or a complaint becomes a task for a person, with a due time.",
              },
              {
                step: "You see it immediately",
                body: "The dashboard shows the call, the outcome, the follow-up queue and whether any doctor status is going stale.",
              },
            ].map((item, index) => (
              <li key={item.step} className="flex gap-6">
                <span
                  className="flex h-8 w-8 shrink-0 items-center justify-center text-body-sm font-semibold"
                  style={{
                    backgroundColor: "var(--color-brand-light)",
                    color: "var(--color-brand)",
                    borderRadius: "var(--radius-card)",
                  }}
                >
                  {index + 1}
                </span>
                <div>
                  <h3 className="text-h3" style={{ color: "var(--color-text-primary)" }}>
                    {item.step}
                  </h3>
                  <p
                    className="mt-1 text-body"
                    style={{ color: "var(--color-text-secondary)", maxWidth: "62ch" }}
                  >
                    {item.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* Closing CTA ------------------------------------------------ */}
        <section
          className="px-6 py-20 text-center"
          style={{
            backgroundColor: "var(--color-surface-elevated)",
            borderTop: "1px solid var(--color-border-subtle)",
          }}
        >
          <div className="mx-auto" style={{ maxWidth: "620px" }}>
            <h2 className="text-h1 text-balance" style={{ color: "var(--color-text-primary)" }}>
              Start with one clinic. Add the rest when it works.
            </h2>
            <p className="mt-4 text-body-lg" style={{ color: "var(--color-text-secondary)" }}>
              Create an account and a clinic in a couple of minutes, or ask an administrator to
              add you to theirs.
            </p>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              <LandingCta size="lg" />
            </div>
          </div>
        </section>
      </main>

      <footer
        className="px-6 py-8"
        style={{
          backgroundColor: "var(--color-surface-elevated)",
          borderTop: "1px solid var(--color-border-subtle)",
        }}
      >
        <div
          className="flex flex-wrap items-center justify-between gap-3"
          style={{ maxWidth: "1200px", margin: "0 auto" }}
        >
          <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
            Clinic Operations — AI assistant for clinics
          </p>
          <p className="text-caption" style={{ color: "var(--color-text-muted)" }}>
            Patient data is scoped to a clinic by the database, not by the interface.
          </p>
        </div>
      </footer>
    </div>
  );
}
