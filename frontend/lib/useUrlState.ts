// useUrlState — sync Zustand sliceStore ↔ URL search params (PRD §URL 即状态).
// On mount, hydrate from URL. On every state change, write to URL.

"use client";

import { useEffect, useRef } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useSliceStore, type DomainKey, type SourceKey, type QualityFilter, type Frequency } from "../stores/sliceStore";

const ARRAY_KEYS = ["symbols", "domains", "dataSources", "qualityFilter"] as const;

export function useUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const hydrated = useRef(false);

  // 1) Hydrate from URL once
  useEffect(() => {
    if (hydrated.current) return;
    hydrated.current = true;
    const s = useSliceStore.getState();
    const get = (k: string) => params.get(k) ?? undefined;
    const next: Partial<typeof s> = {};
    const sym = params.get("symbols");
    if (sym) next.symbols = sym.split(",").filter(Boolean);
    const dt = params.get("decision_time");
    if (dt) next.decisionTime = dt;
    const dc = params.get("decision_clock");
    if (dc === "1605_ET" || dc === "1805_ET") next.decisionClock = dc;
    const start = params.get("start");
    const end = params.get("end");
    if (start && end) next.dateRange = { start, end };
    const dom = params.get("domains");
    if (dom) next.domains = dom.split(",").filter(Boolean) as DomainKey[];
    const src = params.get("sources");
    if (src) next.dataSources = src.split(",").filter(Boolean) as SourceKey[];
    const qf = params.get("quality");
    if (qf) next.qualityFilter = qf.split(",").filter(Boolean) as QualityFilter[];
    const freq = params.get("freq");
    if (freq === "daily" || freq === "weekly" || freq === "monthly") next.frequency = freq as Frequency;
    const panel = params.get("panel");
    if (panel) next.panelId = panel;
    if (Object.keys(next).length) useSliceStore.setState(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2) Subscribe to store changes → write URL
  useEffect(() => {
    const unsub = useSliceStore.subscribe((state) => {
      const sp = new URLSearchParams();
      if (state.symbols.length) sp.set("symbols", state.symbols.join(","));
      if (state.decisionTime) sp.set("decision_time", state.decisionTime);
      if (state.decisionClock !== "1805_ET") sp.set("decision_clock", state.decisionClock);
      if (state.dateRange.start) sp.set("start", state.dateRange.start);
      if (state.dateRange.end) sp.set("end", state.dateRange.end);
      if (state.domains.length) sp.set("domains", state.domains.join(","));
      if (state.dataSources.length) sp.set("sources", state.dataSources.join(","));
      if (state.qualityFilter.length) sp.set("quality", state.qualityFilter.join(","));
      if (state.frequency !== "daily") sp.set("freq", state.frequency);
      if (state.panelId && state.panelId !== "latest") sp.set("panel", state.panelId);
      const next = sp.toString();
      const target = next ? `${pathname}?${next}` : pathname;
      // Avoid loops: only push if different from current
      if (typeof window !== "undefined" && window.location.search !== (next ? `?${next}` : "")) {
        router.replace(target, { scroll: false });
      }
    });
    return unsub;
  }, [pathname, router]);
}
