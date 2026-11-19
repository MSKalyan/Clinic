"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/doctors", label: "Doctors" },
  { href: "/appointments", label: "Appointments" },
  { href: "/patients", label: "Patients" },
  { href: "/follow-ups", label: "Follow-ups" },
  { href: "/calls", label: "Calls" },
  { href: "/conversations", label: "Conversations" },
  { href: "/settings", label: "Settings" },
];

/** Only a clinic administrator may see the provider credentials. */
const ADMIN_LINKS = [{ href: "/integrations", label: "Integrations" }];

/** A compact icon set for the mobile bottom bar. */
const ICONS: Record<string, string> = {
  "/dashboard": "M3 11l9-8 9 8v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z",
  "/doctors": "M12 12a4 4 0 100-8 4 4 0 000 8zm-8 8a8 8 0 0116 0",
  "/appointments": "M7 3v3m10-3v3M4 9h16v12H4z",
  "/patients": "M9 11a4 4 0 100-8 4 4 0 000 8zm8 0a3 3 0 100-6M3 21a6 6 0 0112 0m2-6a5 5 0 015 4",
  "/follow-ups": "M12 8v4l3 2m6-2a9 9 0 11-18 0 9 9 0 0118 0z",
  "/calls": "M5 3h4l2 5-3 2a12 12 0 006 6l2-3 5 2v4a2 2 0 01-2 2A18 18 0 013 5a2 2 0 012-2z",
  "/conversations": "M21 12a8 8 0 01-8 8H7l-4 3V12a8 8 0 018-8 8 8 0 018 8z",
  "/settings": "M12 15a3 3 0 100-6 3 3 0 000 6zm8-3a8 8 0 00-.2-1.7l2-1.6-2-3.4-2.4 1a8 8 0 00-2.9-1.7L14 3h-4l-.5 2.6a8 8 0 00-2.9 1.7l-2.4-1-2 3.4 2 1.6A8 8 0 004 12c0 .6.1 1.2.2 1.7l-2 1.6 2 3.4 2.4-1a8 8 0 002.9 1.7L10 21h4l.5-2.6a8 8 0 002.9-1.7l2.4 1 2-3.4-2-1.6c.1-.5.2-1.1.2-1.7z",
  "/integrations": "M12 4v4m0 8v4M4 12h4m8 0h4M6 6l3 3m6 6l3 3M18 6l-3 3m-6 6l-3 3",
};

export function Nav({ variant = "sidebar" }: { variant?: "sidebar" | "mobile" }) {
  const pathname = usePathname();
  const { activeClinic } = useAuth();
  const isAdmin = activeClinic?.role === "clinic_admin";

  const links = isAdmin ? [...LINKS, ...ADMIN_LINKS] : LINKS;

  if (variant === "mobile") {
    const primary = links.filter((link) => link.href !== "/settings" && link.href !== "/integrations");
    return (
      <nav
        className="fixed inset-x-0 bottom-0 z-40 flex items-stretch justify-around border-t border-slate-200 md:hidden"
        style={{ backgroundColor: "var(--color-surface-elevated)", paddingBottom: "env(safe-area-inset-bottom)" }}
        aria-label="Main navigation"
      >
        {primary.map((link) => {
          const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
          return (
            <Link
              key={link.href}
              href={link.href}
              aria-current={active ? "page" : undefined}
              aria-label={link.label}
              className="flex flex-1 flex-col items-center gap-1 py-2"
              style={{ color: active ? "var(--color-brand)" : "var(--color-text-muted)" }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d={ICONS[link.href] ?? ICONS["/dashboard"]} />
              </svg>
              <span className="text-[10px] font-medium">{link.label}</span>
            </Link>
          );
        })}
      </nav>
    );
  }

  return (
    <nav className="flex flex-col gap-1" aria-label="Main navigation">
      {links.map((link) => {
        const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={`nav-link ${active ? "active" : ""}`}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
