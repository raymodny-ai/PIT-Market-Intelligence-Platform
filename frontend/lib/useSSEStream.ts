// useSSEStream — auto-reconnecting SSE client (PRD §SSEProgressBar).
// Reads from `url`, parses event: lines, supports Last-Event-ID resume
// on reconnect with exponential backoff (max 3 retries).

"use client";

import { useEffect, useRef, useState } from "react";
import { useReportStore } from "../stores/reportStore";

export interface SSEMessage {
  id?: string;
  event?: string;
  data: any;
}

export interface UseSSEStreamOpts {
  url: string;
  enabled: boolean;
  onMessage: (msg: SSEMessage) => void;
  onError?: (e: Event) => void;
  onComplete?: () => void;
  maxRetries?: number;
}

export function useSSEStream(opts: UseSSEStreamOpts) {
  const { url, enabled, onMessage, onError, onComplete, maxRetries = 3 } = opts;
  const [status, setStatus] = useState<"idle" | "connecting" | "open" | "closed" | "error">("idle");
  const [retryCount, setRetryCount] = useState(0);
  const lastEventIdRef = useRef<string | undefined>(undefined);
  const recordReconnect = useReportStore((s) => s.recordReconnect);

  useEffect(() => {
    if (!enabled || !url) return;
    let es: EventSource | null = null;
    let cancelled = false;
    let backoff = 500;

    const connect = () => {
      if (cancelled) return;
      setStatus("connecting");
      // EventSource doesn't support custom headers; pass last-event-id as
      // a query string instead (server is expected to honour ?last_event_id=).
      const sep = url.includes("?") ? "&" : "?";
      const lastId = lastEventIdRef.current;
      const fullUrl = lastId ? `${url}${sep}last_event_id=${encodeURIComponent(lastId)}` : url;
      es = new EventSource(fullUrl, { withCredentials: false });

      es.onopen = () => {
        setStatus("open");
        setRetryCount(0);
        backoff = 500;
      };

      es.onmessage = (ev) => {
        const msg: SSEMessage = {
          id: ev.lastEventId || undefined,
          data: ev.data,
        };
        if (msg.id) lastEventIdRef.current = msg.id;
        let parsed: any = msg.data;
        try { parsed = JSON.parse(msg.data); } catch { /* keep as string */ }
        onMessage({ ...msg, data: parsed });
      };

      // Some servers send typed events
      ["stage", "progress", "finding", "complete", "error"].forEach((evt) => {
        if (!es) return;
        es.addEventListener(evt, (ev: any) => {
          let parsed: any = ev.data;
          try { parsed = JSON.parse(ev.data); } catch { /* keep */ }
          const msg: SSEMessage = { id: ev.lastEventId, event: evt, data: parsed };
          if (msg.id) lastEventIdRef.current = msg.id;
          onMessage(msg);
          if (evt === "complete") {
            setStatus("closed");
            onComplete?.();
          }
        });
      });

      es.onerror = (e) => {
        if (cancelled) return;
        setStatus("error");
        onError?.(e);
        es?.close();
        // Retry with exponential backoff
        setRetryCount((n) => {
          const next = n + 1;
          if (next > maxRetries) {
            setStatus("closed");
            return n;
          }
          recordReconnect();
          setTimeout(connect, backoff);
          backoff = Math.min(backoff * 2, 8000);
          return next;
        });
      };
    };

    connect();
    return () => {
      cancelled = true;
      es?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, enabled, maxRetries]);

  return { status, retryCount };
}
