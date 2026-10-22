"use client";

/**
 * A small data-fetching hook.
 *
 * It re-runs whenever the active clinic changes (the API is scoped to it)
 * and whenever the caller asks for a reload. The `key` argument is for
 * filters that live in component state -- changing it re-fetches.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import type { ApiClient } from "@/lib/api";

export function useApiData<T>(
  fetcher: (api: ApiClient, signal: AbortSignal) => Promise<T>,
  key = "",
) {
  const { api, activeClinicId } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!activeClinicId) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    fetcherRef
      .current(api, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setLoading(false);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setError(cause);
        setLoading(false);
      });

    return () => controller.abort();
  }, [api, activeClinicId, key, nonce]);

  return { data, error, loading, reload };
}
