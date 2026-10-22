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

export function Nav() {
  const pathname = usePathname();
  const { activeClinic } = useAuth();
  const isAdmin = activeClinic?.role === "clinic_admin";

  const links = isAdmin ? [...LINKS, ...ADMIN_LINKS] : LINKS;

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
