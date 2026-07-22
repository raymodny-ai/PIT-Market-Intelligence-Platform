// sliceStore — global UI slice state (PRD §全局状态设计 / T-11).
// Mirrors /v1/panels/{id}/slice request body and is the source of truth
// for FilterRail, charts, and AG Grid.

"use client";

import { create } from "zustand";

export type DomainKey = "price_volume" | "macro_rates" | "cot_positioning" | "short_flow";
export type SourceKey = "yfinance" | "cftc" | "finra" | "fred_alfred" | "sec_edgar" | "etf_shares";
export type QualityFilter = "VALID" | "STALE" | "INFERRED" | "FAILED" | "DEGRADED";
export type Frequency = "daily" | "weekly" | "monthly";

export const DOMAINS: { key: DomainKey; label: string; color: string }[] = [
  { key: "price_volume", label: "价格 & 成交量", color: "#6366f1" },
  { key: "macro_rates", label: "宏观 & 利率", color: "#0ea5e9" },
  { key: "cot_positioning", label: "COT 持仓", color: "#10b981" },
  { key: "short_flow", label: "短卖流量", color: "#f59e0b" },
];

export const SOURCES: { key: SourceKey; label: string }[] = [
  { key: "yfinance", label: "yfinance" },
  { key: "cftc", label: "CFTC COT" },
  { key: "finra", label: "FINRA Reg SHO" },
  { key: "fred_alfred", label: "FRED ALFRED" },
  { key: "sec_edgar", label: "SEC EDGAR" },
  { key: "etf_shares", label: "ETF Shares" },
];

export const QUALITY_OPTIONS: QualityFilter[] = [
  "VALID", "STALE", "INFERRED", "DEGRADED", "FAILED",
];

export const FREQUENCIES: Frequency[] = ["daily", "weekly", "monthly"];

export interface SliceState {
  symbols: string[];
  decisionTime: string;          // ISO 8601
  decisionClock: "1605_ET" | "1805_ET";
  dateRange: { start: string; end: string };
  domains: DomainKey[];
  dataSources: SourceKey[];
  qualityFilter: QualityFilter[];
  frequency: Frequency;
  panelId: string;               // current active panel
  // setters
  setSymbols: (s: string[]) => void;
  toggleSymbol: (s: string) => void;
  setDecisionTime: (t: string) => void;
  setDecisionClock: (c: "1605_ET" | "1805_ET") => void;
  setDateRange: (r: { start: string; end: string }) => void;
  setDomains: (d: DomainKey[]) => void;
  toggleDomain: (d: DomainKey) => void;
  setDataSources: (s: SourceKey[]) => void;
  toggleDataSource: (s: SourceKey) => void;
  setQualityFilter: (q: QualityFilter[]) => void;
  toggleQualityFilter: (q: QualityFilter) => void;
  setFrequency: (f: Frequency) => void;
  setPanelId: (p: string) => void;
  reset: () => void;
}

// Default state is deterministic across SSR and CSR to avoid hydration
// mismatches. Values depending on "now" are intentionally sentinel; the
// client refreshes them via useEffect after first paint. Components that
// render time-sensitive data must use the `useMounted()` flag so they only
// render on the client.
const DEFAULT_STATE = {
  symbols: ["SPY", "QQQ", "GLD", "SLV"] as string[],
  decisionTime: "1970-01-01T00:00:00.000Z",
  decisionClock: "1805_ET" as const,
  dateRange: {
    start: "1970-01-01",
    end: "1970-01-01",
  },
  domains: ["price_volume" as DomainKey],
  dataSources: ["yfinance" as SourceKey, "fred_alfred" as SourceKey],
  qualityFilter: ["VALID" as QualityFilter, "DEGRADED" as QualityFilter, "INFERRED" as QualityFilter],
  frequency: "daily" as Frequency,
  panelId: "latest",
};

export const useSliceStore = create<SliceState>((set, get) => ({
  ...DEFAULT_STATE,

  setSymbols: (s) => set({ symbols: s }),
  toggleSymbol: (s) => set({
    symbols: get().symbols.includes(s)
      ? get().symbols.filter((x) => x !== s)
      : [...get().symbols, s],
  }),
  setDecisionTime: (t) => set({ decisionTime: t }),
  setDecisionClock: (c) => set({ decisionClock: c }),
  setDateRange: (r) => set({ dateRange: r }),
  setDomains: (d) => set({ domains: d }),
  toggleDomain: (d) => set({
    domains: get().domains.includes(d)
      ? get().domains.filter((x) => x !== d)
      : [...get().domains, d],
  }),
  setDataSources: (s) => set({ dataSources: s }),
  toggleDataSource: (s) => set({
    dataSources: get().dataSources.includes(s)
      ? get().dataSources.filter((x) => x !== s)
      : [...get().dataSources, s],
  }),
  setQualityFilter: (q) => set({ qualityFilter: q }),
  toggleQualityFilter: (q) => set({
    qualityFilter: get().qualityFilter.includes(q)
      ? get().qualityFilter.filter((x) => x !== q)
      : [...get().qualityFilter, q],
  }),
  setFrequency: (f) => set({ frequency: f }),
  setPanelId: (p) => set({ panelId: p }),
  reset: () => set(DEFAULT_STATE),
}));
