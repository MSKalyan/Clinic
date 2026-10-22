"use client";

/**
 * The clinic switcher.
 *
 * The clinic is part of the session, not a per-request choice: it is sent
 * as `X-Clinic-Id` on every call. The backend resolves the tenant from the
 * membership, so switching here only changes *which* of the user's clinics
 * the request is scoped to -- it cannot widen access.
 */
import { useAuth } from "@/components/auth-provider";
import { Select } from "@/components/ui";

export function ClinicSwitcher() {
  const { clinics, activeClinicId, switchClinic, activeClinic } = useAuth();

  if (clinics.length === 0) {
    return (
      <span className="text-caption" style={{ color: "var(--color-text-muted)" }}>
        No clinic membership
      </span>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <label htmlFor="clinic-switcher" className="text-caption" style={{ color: "var(--color-text-muted)" }}>
        Clinic
      </label>
      <Select
        id="clinic-switcher"
        value={activeClinicId ?? ""}
        onChange={(event) => switchClinic(event.target.value)}
        aria-label="Select clinic"
      >
        {clinics.map((clinic) => (
          <option key={clinic.clinic_id} value={clinic.clinic_id}>
            {clinic.name}
          </option>
        ))}
      </Select>
      {activeClinic && (
        <span className="hidden text-caption sm:inline" style={{ color: "var(--color-text-muted)" }}>
          {activeClinic.role.replace(/_/g, " ")} · {activeClinic.timezone}
        </span>
      )}
    </div>
  );
}