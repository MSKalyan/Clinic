"use client";

/**
 * Live clinic events over WebSocket.
 *
 * One socket is kept per hook instance with exponential-backoff reconnect.
 * Thread subscriptions are tracked as *desired state*, so a component can call
 * `subscribe()` before the socket finishes connecting; the subscriptions are
 * replayed automatically every time the socket opens (including reconnects).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";

export interface ClinicEvent {
  event: string;
  data: Record<string, unknown>;
  at?: string;
}

export type EventHandler = (event: ClinicEvent) => void;

const WS_BASE =
  process.env.NEXT_PUBLIC_WS_BASE_URL ??
  (typeof window !== "undefined"
    ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.hostname}:8000`
    : "ws://localhost:8000");

export function useClinicSocket(onEvent: EventHandler) {
  const { activeClinicId, accessToken } = useAuth();
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const desiredRef = useRef<Set<string>>(new Set());
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, []);

  const send = useCallback((action: "subscribe" | "unsubscribe", conversationId: string) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ action, conversation_id: conversationId }));
    }
  }, []);

  useEffect(() => {
    if (!activeClinicId || !accessToken) {
      setConnected(false);
      return;
    }

    let disposed = false;

    const connect = () => {
      if (disposed || !mountedRef.current) return;
      const url = `${WS_BASE}/ws/clinic/${encodeURIComponent(activeClinicId)}/?token=${encodeURIComponent(accessToken)}`;
      let socket: WebSocket;
      try {
        socket = new WebSocket(url);
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        if (disposed) return;
        retryRef.current = 0;
        setConnected(true);
        // Replay every thread the consumer wants, on each (re)connect.
        desiredRef.current.forEach((id) =>
          socket.send(JSON.stringify({ action: "subscribe", conversation_id: id })),
        );
      };

      socket.onmessage = (message) => {
        if (disposed) return;
        try {
          const parsed = JSON.parse(message.data as string) as ClinicEvent;
          if (parsed && parsed.event) handlerRef.current(parsed);
        } catch {
          // Ignore malformed frames; the connection stays healthy.
        }
      };

      socket.onclose = () => {
        if (disposed) return;
        setConnected(false);
        scheduleReconnect();
      };

      socket.onerror = () => {
        // onclose always follows an error, so reconnect happens there.
        try {
          socket.close();
        } catch {
          // already closed
        }
      };
    };

    const scheduleReconnect = () => {
      if (disposed || !mountedRef.current) return;
      const delay = Math.min(1000 * 2 ** retryRef.current, 15000);
      retryRef.current += 1;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(connect, delay);
    };

    connect();
    return () => {
      disposed = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      const socket = socketRef.current;
      if (socket) {
        socket.onclose = null;
        socket.onerror = null;
        socket.close();
      }
      socketRef.current = null;
      setConnected(false);
    };
  }, [activeClinicId, accessToken]);

  const subscribe = useCallback(
    (conversationId: string) => {
      desiredRef.current.add(conversationId);
      send("subscribe", conversationId);
    },
    [send],
  );

  const unsubscribe = useCallback(
    (conversationId: string) => {
      desiredRef.current.delete(conversationId);
      send("unsubscribe", conversationId);
    },
    [send],
  );

  return { connected, subscribe, unsubscribe };
}
