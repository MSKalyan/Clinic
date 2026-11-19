"use client";

/**
 * Session state for the dashboard.
 *
 * The tokens live in `localStorage` because the dashboard is a
 * single-page app that talks to the API directly from the browser. The
 * *clinic* is part of the session too: it is carried on every request as
 * `X-Clinic-Id`, and the backend re-checks that the signed-in user is
 * actually a member of it.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClient, ApiError } from "@/lib/api";
import type { ClinicMembership, TokenPair, User } from "@/lib/types";

const TOKEN_KEY = "clinic-ops.tokens";
const CLINIC_KEY = "clinic-ops.clinicId";

interface AuthState {
  user: User | null;
  clinics: ClinicMembership[];
  activeClinicId: string | null;
  activeClinic: ClinicMembership | null;
  status: "loading" | "authenticated" | "anonymous";
}

interface AuthContextValue extends AuthState {
  api: ApiClient;
  /** Current access token, used to authenticate the live WebSocket. */
  accessToken: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  switchClinic: (clinicId: string) => void;
  /** Install a set of tokens and resolve the memberships that go with them. */
  establishSession: (tokens: TokenPair, user: User | null) => Promise<ClinicMembership[]>;
  /** Re-read the memberships, after a clinic was created or a member added. */
  refreshClinics: () => Promise<ClinicMembership[]>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readTokens(): TokenPair | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as TokenPair;
    return parsed?.access && parsed?.refresh ? parsed : null;
  } catch {
    return null;
  }
}

function writeTokens(tokens: TokenPair | null) {
  if (typeof window === "undefined") return;
  if (tokens) window.localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
  else window.localStorage.removeItem(TOKEN_KEY);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [tokens, setTokens] = useState<TokenPair | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [clinics, setClinics] = useState<ClinicMembership[]>([]);
  const [activeClinicId, setActiveClinicId] = useState<string | null>(null);
  const [status, setStatus] = useState<AuthState["status"]>("loading");

  // The API client reads the session through refs, so it never has to be
  // rebuilt (and never goes stale) when the session changes.
  const tokensRef = useRef<TokenPair | null>(null);
  const clinicRef = useRef<string | null>(null);

  useEffect(() => {
    tokensRef.current = tokens;
  }, [tokens]);
  useEffect(() => {
    clinicRef.current = activeClinicId;
  }, [activeClinicId]);

  const api = useMemo(
    () =>
      new ApiClient({
        getTokens: () => tokensRef.current,
        getClinicId: () => clinicRef.current,
        onRefreshed: (fresh) => {
          tokensRef.current = fresh;
          writeTokens(fresh);
          setTokens(fresh);
        },
        onSessionLost: () => {
          tokensRef.current = null;
          writeTokens(null);
          setTokens(null);
          setUser(null);
          setClinics([]);
          setStatus("anonymous");
          router.replace("/login");
        },
      }),
    [router],
  );

  /**
   * Put the tokens where the API client can see them.
   *
   * The client reads the session through a ref rather than through state,
   * so this has to happen *before* the next request goes out. Installing
   * the tokens later -- after a request that needs them -- means that
   * request goes out unauthenticated.
   */
  const installTokens = useCallback((nextTokens: TokenPair | null) => {
    tokensRef.current = nextTokens;
    writeTokens(nextTokens);
    setTokens(nextTokens);
  }, []);

  /**
   * Choose the clinic this session works in.
   *
   * The previously selected clinic is kept when the user is still a member
   * of it; otherwise the first membership wins. With no memberships at
   * all the session is left without a clinic, which is what the "no clinic
   * selected" screen is for.
   */
  const selectClinic = useCallback((memberships: ClinicMembership[]) => {
    const stored = typeof window !== "undefined" ? window.localStorage.getItem(CLINIC_KEY) : null;
    const usable = memberships.some((m) => m.clinic_id === stored);
    const chosen = usable ? (stored as string) : (memberships[0]?.clinic_id ?? null);
    if (chosen) window.localStorage.setItem(CLINIC_KEY, chosen);
    else window.localStorage.removeItem(CLINIC_KEY);

    clinicRef.current = chosen;
    setActiveClinicId(chosen);
  }, []);

  const applySession = useCallback(
    (nextTokens: TokenPair, memberships: ClinicMembership[]) => {
      installTokens(nextTokens);
      selectClinic(memberships);
    },
    [installTokens, selectClinic],
  );

  // Restore an existing session on first paint.
  useEffect(() => {
    let cancelled = false;
    const stored = readTokens();
    if (!stored) {
      setStatus("anonymous");
      return;
    }
    tokensRef.current = stored;
    setTokens(stored);

    api
      .get<{ user: User | null; clinics: ClinicMembership[] }>("/auth/me/")
      .then((payload) => {
        if (cancelled) return;
        setUser(payload.user);
        setClinics(payload.clinics);
        applySession(stored, payload.clinics);
        setStatus("authenticated");
      })
      .catch(() => {
        if (cancelled) return;
        tokensRef.current = null;
        writeTokens(null);
        setStatus("anonymous");
      });

    return () => {
      cancelled = true;
    };
  }, [api, applySession]);

  /**
   * Resolve the memberships for a set of tokens and make them the session.
   *
   * The tokens are installed *first*. The API client reads them from a
   * ref, so fetching the memberships before installing the tokens would
   * send the request with the previous session's token -- or with none at
   * all, which the server answers with an empty clinic list. That is what
   * made a fresh sign-in land on "no clinic selected" even for a user
   * with a perfectly good membership.
   */
  const establishSession = useCallback(
    async (nextTokens: TokenPair, nextUser: User | null) => {
      installTokens(nextTokens);
      setUser(nextUser);

      // The token is passed explicitly rather than read from the session.
      // The session's token lives in a ref, and a request that depends on
      // that ref having been updated already is a race -- and losing it
      // means an empty clinic list and a "no clinic selected" screen.
      const memberships = await api
        .get<{ clinics: ClinicMembership[] }>("/auth/me/", {
          token: nextTokens.access,
        })
        .then((r) => r.clinics ?? [])
        .catch(() => [] as ClinicMembership[]);

      setClinics(memberships);
      selectClinic(memberships);
      setStatus("authenticated");
      return memberships;
    },
    [api, installTokens, selectClinic],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const payload = await api.post<{ user: User; tokens: TokenPair }>("/auth/login/", {
        email,
        password,
      });
      await establishSession(payload.tokens, payload.user);
    },
    [api, establishSession],
  );

  /**
   * Re-read the memberships and re-pick the clinic.
   *
   * Needed after something outside the session changes it -- creating a
   * clinic, or being added to one by an administrator.
   */
  const refreshClinics = useCallback(async () => {
    const payload = await api
      .get<{ user: User | null; clinics: ClinicMembership[] }>("/auth/me/")
      .then((r) => r)
      .catch(() => null);
    if (!payload) return [];
    const memberships = payload.clinics ?? [];
    setUser(payload.user);
    setClinics(memberships);
    selectClinic(memberships);
    return memberships;
  }, [api, selectClinic]);

  const logout = useCallback(() => {
    tokensRef.current = null;
    clinicRef.current = null;
    writeTokens(null);
    if (typeof window !== "undefined") window.localStorage.removeItem(CLINIC_KEY);
    setTokens(null);
    setUser(null);
    setClinics([]);
    setActiveClinicId(null);
    setStatus("anonymous");
    router.replace("/login");
  }, [router]);

  const switchClinic = useCallback((clinicId: string) => {
    clinicRef.current = clinicId;
    setActiveClinicId(clinicId);
    if (typeof window !== "undefined") window.localStorage.setItem(CLINIC_KEY, clinicId);
  }, []);

  const activeClinic = useMemo(
    () => clinics.find((c) => c.clinic_id === activeClinicId) ?? null,
    [clinics, activeClinicId],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      clinics,
      activeClinicId,
      activeClinic,
      status,
      api,
      accessToken: tokens?.access ?? null,
      login,
      logout,
      switchClinic,
      establishSession,
      refreshClinics,
    }),
    [
      user,
      clinics,
      activeClinicId,
      activeClinic,
      status,
      api,
      tokens,
      login,
      logout,
      switchClinic,
      establishSession,
      refreshClinics,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside an AuthProvider.");
  return context;
}

export { ApiError };
