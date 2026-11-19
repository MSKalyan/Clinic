"use client";

/**
 * The signed-in shell: sidebar, header and the clinic switcher.
 */
import Link from "next/link";

import { ClinicSwitcher } from "@/components/clinic-switcher";
import { Nav } from "@/components/nav";
import { RequireAuth } from "@/components/require-auth";
import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui";
import { NoClinic } from "@/components/no-clinic";

function Shell({ children }: { children: React.ReactNode }) {
  const { user, logout, activeClinicId, status } = useAuth();

  return (
    <div className="flex min-h-screen" style={{ backgroundColor: "var(--color-surface)" }}>
      <aside
        className="hidden w-64 shrink-0 flex-col justify-between border-r border-slate-200 p-5 md:flex"
        style={{ backgroundColor: "var(--color-surface-elevated)" }}
      >
        <div>
          <Link href="/dashboard" className="mb-8 block" style={{ textDecoration: "none" }}>
            <p
              className="text-h3 font-semibold"
              style={{ color: "var(--color-text-primary)", letterSpacing: "-0.01em" }}
            >
              Clinic Operations
            </p>
            <p
              className="text-caption mt-1"
              style={{
                color: "var(--color-text-muted)",
                letterSpacing: "0.05em",
                textTransform: "uppercase",
              }}
            >
              AI assistant control room
            </p>
          </Link>
          <Nav />
        </div>
        <div className="space-y-3 border-t border-slate-200 pt-4">
          <div>
            <p
              className="truncate text-body font-medium"
              style={{ color: "var(--color-text-primary)" }}
            >
              {user?.email ?? "Signed in"}
            </p>
            <p className="text-caption mt-0.5" style={{ color: "var(--color-text-muted)" }}>
              {user?.is_platform_admin ? "Platform administrator" : "Clinic staff"}
            </p>
          </div>
          <Button variant="ghost" onClick={logout} className="w-full justify-start">
            Sign out
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3"
          style={{ backgroundColor: "var(--color-surface-elevated)" }}
        >
          <div className="flex items-center gap-3 md:hidden">
            <Link
              href="/dashboard"
              className="text-h3 font-semibold"
              style={{ color: "var(--color-text-primary)", textDecoration: "none" }}
            >
              Clinic Ops
            </Link>
          </div>
          <div className="hidden md:block" />
          {activeClinicId ? <ClinicSwitcher /> : null}
        </header>

        {!activeClinicId ? (
          <main className="flex flex-1 items-center justify-center p-8">
            {status === "authenticated" ? (
              <NoClinic />
            ) : (
              <div
                className="max-w-md rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900"
                style={{
                  borderRadius: "var(--radius-card)",
                  borderColor: "var(--color-warning)",
                  backgroundColor: "var(--color-warning-light)",
                  color: "var(--color-warning)",
                }}
              >
                <p className="font-semibold">No clinic selected</p>
                <p className="mt-1">
                  Your account is not an active member of any clinic yet. Ask a clinic administrator
                  to invite you.
                </p>
              </div>
            )}
          </main>
        ) : (
          <main className="flex-1 p-5 pb-24 md:p-8">{children}</main>
        )}
      </div>
      {activeClinicId ? <Nav variant="mobile" /> : null}
    </div>
  );
}

export default function OpsLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <Shell>{children}</Shell>
    </RequireAuth>
  );
}
