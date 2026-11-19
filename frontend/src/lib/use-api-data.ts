"use client";

/**
 * A small data-fetching hook with stale-while-revalidate behaviour.
 *
 * Previous data stays on screen while a refresh is in flight, so changing a
 * filter never blanks the page with a spinner. Only the very first load (no
 * cached data for this key) shows the loading state.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import type { ApiClient } from "@/lib/api";

/** Session-scoped cache so navigating back to a screen is instant. */
const cache = new Map<string, unknown>();

export function useApiData<T>(
  fetcher: (api: ApiClient, signal: AbortSignal) => Promise<T>,
  key = "",
) {
  const { api, activeClinicId } = useAuth();
  const cacheKey = `${activeClinicId ?? "anon"}:${key}`;
  const [data, setData] = useState<T | null>(() => (cache.get(cacheKey) as T) ?? null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(() => !cache.has(cacheKey));
  const [refreshing, setRefreshing] = useState(false);
  const [nonce, setNonce] = useState(0);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!activeClinicId) {
      setLoading(false);
      setData(null);
      return;
    }

    const controller = new AbortController();
    const cached = cache.has(cacheKey);
    if (cached) setRefreshing(true);
    else setLoading(true);

    fetcherRef
      .current(api, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        cache.set(cacheKey, result);
        setData(result);
        setError(null);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        // Keep stale data visible but surface the error.
        setError(cause);
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setLoading(false);
        setRefreshing(false);
      });

    return () => controller.abort();
  }, [api, activeClinicId, cacheKey, nonce]);

  const setDataDirect = useCallback(
    (updater: (current: T | null) => T | null) => {
      setData((current) => {
        const next = updater(current);
        if (next !== null) cache.set(cacheKey, next);
        return next;
      });
    },
    [cacheKey],
  );

  return { data, error, loading, refreshing, reload, setData: setDataDirect };
}
