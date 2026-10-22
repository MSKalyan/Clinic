/**
 * The API client.
 *
 * Two rules from the backend are baked in here:
 *
 * 1. **The tenant comes from the header.** Every request that touches
 *    tenant data carries `X-Clinic-Id`. The backend ignores that header for
 *    service tokens, but for staff it selects the clinic the signed-in user
 *    is a member of -- it can never select a clinic the user is not a
 *    member of.
 * 2. **Errors arrive in one envelope.** `{"error": {code, message, details,
 *    request_id}}`. `ApiError` keeps that shape so a screen can show the
 *    message the backend chose.
 */
import type { TokenPair } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(
    message: string,
    status: number,
    code: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  /**
   * Use this access token for this request instead of the session's.
   *
   * The session's token lives in a ref that is updated when the session
   * changes. A request that depends on that ref having been updated *by
   * the time the request goes out* is a race: install the token after
   * starting the request and it leaves without an ``Authorization``
   * header. Passing the token explicitly removes the race entirely.
   *
   * This is what ``/auth/me/`` uses right after a sign-in, where the
   * session's token is by definition the one that was just issued.
   */
  token?: string | null;
}

export interface AuthHandlers {
  /** The tokens to use, or null when the session has ended. */
  getTokens: () => TokenPair | null;
  /** The clinic the session is currently working in, if any. */
  getClinicId: () => string | null;
  /** Called with fresh tokens after a successful refresh. */
  onRefreshed: (tokens: TokenPair) => void;
  /** Called when the session cannot be recovered. */
  onSessionLost: () => void;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = new URL(path.startsWith("http") ? path : `${API_BASE}${path}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function readError(response: Response): Promise<ApiError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const envelope = (payload as { error?: Record<string, unknown> } | null)?.error;
  if (envelope) {
    return new ApiError(
      String(envelope.message ?? "Something went wrong."),
      response.status,
      String(envelope.code ?? "error"),
      (envelope.details as Record<string, unknown>) ?? {},
    );
  }
  return new ApiError(
    `Request failed (${response.status}).`,
    response.status,
    "error",
  );
}

/** A client bound to one session. */
export class ApiClient {
  private readonly handlers: AuthHandlers;
  private refreshing: Promise<TokenPair | null> | null = null;

  constructor(handlers: AuthHandlers) {
    this.handlers = handlers;
  }

  /**
   * Perform a request, refreshing the access token once if it has expired.
   *
   * The refresh is de-duplicated: several parallel requests that all get a
   * 401 share one refresh round-trip instead of stampeding the endpoint.
   */
  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const response = await this.send(path, options, false);
    if (response.status === 401) {
      const refreshed = await this.refresh();
      if (refreshed) {
        const retry = await this.send(path, options, true);
        if (!retry.ok) throw await readError(retry);
        return (await retry.json()) as T;
      }
      this.handlers.onSessionLost();
      throw new ApiError("Your session has expired. Please sign in again.", 401, "session_expired");
    }
    if (!response.ok) throw await readError(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  get<T>(
    path: string,
    options?: Omit<RequestOptions, "method" | "body">,
  ): Promise<T> {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  post<T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ): Promise<T> {
    return this.request<T>(path, { ...options, method: "POST", body });
  }

  patch<T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ): Promise<T> {
    return this.request<T>(path, { ...options, method: "PATCH", body });
  }

  put<T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ): Promise<T> {
    return this.request<T>(path, { ...options, method: "PUT", body });
  }

  delete<T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ): Promise<T> {
    return this.request<T>(path, { ...options, method: "DELETE", body });
  }

  private async send(
    path: string,
    options: RequestOptions,
    isRetry: boolean,
  ): Promise<Response> {
    const tokens = this.handlers.getTokens();
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";

    // An explicit token wins over the session's, so a request that needs a
    // brand new token does not depend on the ref having been updated yet.
    const access = options.token ?? tokens?.access;
    if (access) headers["Authorization"] = `Bearer ${access}`;

    const clinicId = this.handlers.getClinicId?.();
    if (clinicId) headers["X-Clinic-Id"] = clinicId;

    return fetch(buildUrl(path, options.params), {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      cache: "no-store",
    });
  }

  private async refresh(): Promise<TokenPair | null> {
    if (this.refreshing) return this.refreshing;
    const tokens = this.handlers.getTokens();
    if (!tokens?.refresh) return null;

    this.refreshing = (async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/refresh/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh: tokens.refresh }),
        });
        if (!response.ok) return null;
        const payload = (await response.json()) as { tokens: TokenPair };
        this.handlers.onRefreshed(payload.tokens);
        return payload.tokens;
      } catch {
        return null;
      } finally {
        this.refreshing = null;
      }
    })();

    return this.refreshing;
  }
}
