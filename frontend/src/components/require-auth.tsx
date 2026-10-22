"use client";

import { useAuth } from "@/components/auth-provider";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Spinner } from "@/components/ui";

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center" style={{ backgroundColor: "var(--color-surface)" }}>
        <Spinner label="Loading session…" size="lg" />
      </div>
    );
  }
  if (status === "anonymous") return null;
  return <>{children}</>;
}