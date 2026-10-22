/**
 * The API client's contract with the session.
 *
 * The bug this file exists to prevent: after signing in, the dashboard
 * asked the server which clinics the user belongs to. The request went
 * out with the *previous* session's token -- or none at all -- because
 * the session's token lives in a ref that is updated separately. The
 * server answered `{"user": null, "clinics": []}`, and the user landed on
 * "no clinic selected" even though their membership was perfectly valid.
 *
 * The fix is a per-request token override: a request that needs a
 * brand-new token says so, and does not depend on the ref's timing.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ApiClient, ApiError } from "../src/lib/api.ts";

interface Recorded {
  url: string;
  headers: Record<string, string>;
}

/**
 * A fake fetch that records the requests and answers with whatever the
 * test wants.
 */
function fakeFetch(
  responses: Record<string, unknown>,
  recorded: Recorded[],
): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const headers: Record<string, string> = {};
    for (const [key, value] of Object.entries(
      (init?.headers ?? {}) as Record<string, string>,
    )) {
      headers[key] = value;
    }
    recorded.push({ url, headers });

    const path = new URL(url).pathname;
    const body = responses[path] ?? { error: { code: "not_found", message: "no stub" } };
    // An error envelope means a 4xx; a body without one is a 200.
    const status =
      body === null ? 404 : "error" in (body as Record<string, unknown>) ? 400 : 200;

    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
}

function client(sessionToken: string | null) {
  const recorded: Recorded[] = [];
  const api = new ApiClient({
    getTokens: () => (sessionToken ? { access: sessionToken, refresh: "r" } : null),
    getClinicId: () => null,
    onRefreshed: () => {},
    onSessionLost: () => {},
  });
  return { api, recorded };
}

describe("ApiClient token handling", () => {
  it("sends the session's token when no override is given", async () => {
    const { api, recorded } = client("session-token");
    globalThis.fetch = fakeFetch({ "/api/v1/auth/me/": { clinics: [] } }, recorded);

    await api.get("/auth/me/");

    assert.equal(recorded[0].headers["Authorization"], "Bearer session-token");
  });

  it("sends an explicitly provided token instead of the session's", async () => {
    const { api, recorded } = client("stale-session-token");
    globalThis.fetch = fakeFetch({ "/api/v1/auth/me/": { clinics: [] } }, recorded);

    await api.get("/auth/me/", { token: "brand-new-token" });

    assert.equal(recorded[0].headers["Authorization"], "Bearer brand-new-token");
  });

  it("sends the explicit token even when the session has none", async () => {
    const { api, recorded } = client(null);
    globalThis.fetch = fakeFetch({ "/api/v1/auth/me/": { clinics: [] } }, recorded);

    await api.get("/auth/me/", { token: "brand-new-token" });

    assert.equal(recorded[0].headers["Authorization"], "Bearer brand-new-token");
  });

  it("sends no Authorization header when there is no token at all", async () => {
    const { api, recorded } = client(null);
    globalThis.fetch = fakeFetch({ "/api/v1/auth/me/": { clinics: [] } }, recorded);

    await api.get("/auth/me/");

    assert.equal(recorded[0].headers["Authorization"], undefined);
  });

  it("still carries the clinic header alongside an explicit token", async () => {
    const recorded: Recorded[] = [];
    const api = new ApiClient({
      getTokens: () => ({ access: "session-token", refresh: "r" }),
      getClinicId: () => "clinic-1",
      onRefreshed: () => {},
      onSessionLost: () => {},
    });
    globalThis.fetch = fakeFetch({ "/api/v1/auth/me/": { clinics: [] } }, recorded);

    await api.get("/auth/me/", { token: "brand-new-token" });

    assert.equal(recorded[0].headers["X-Clinic-Id"], "clinic-1");
  });
});

describe("ApiError", () => {
  it("keeps the backend's error envelope", async () => {
    const recorded: Recorded[] = [];
    const api = new ApiClient({
      getTokens: () => null,
      getClinicId: () => null,
      onRefreshed: () => {},
      onSessionLost: () => {},
    });
    globalThis.fetch = fakeFetch(
      {
        "/api/v1/clinics/": {
          error: {
            code: "invalid",
            message: 'slug: Enter a valid "slug" consisting of letters, numbers, underscores or hyphens.',
            details: { fields: { slug: ["…"] } },
            request_id: "req-1",
          },
        },
      },
      recorded,
    );

    await assert.rejects(
      () => api.post("/clinics/", { slug: "not a slug" }),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, 400);
        assert.equal(error.code, "invalid");
        assert.match(error.message, /^slug: Enter a valid "slug"/);
        return true;
      },
    );
  });
});
