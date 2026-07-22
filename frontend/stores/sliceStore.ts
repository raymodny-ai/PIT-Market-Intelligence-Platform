// SliceStore — global UI slice state (PRD §11.2).
"use client";

import { create } from "zustand";

export type DecisionClock = "1605_ET" | "1805_ET";
export type ViewMode = "overview" | "research" | "replay" | "audit";

export interface SliceState {
  activePanelId: string | "latest";
  decisionTime: string;
  decisionClock: DecisionClock;
  selectedSymbols: string[];
  selectedDomains: string[];
  selectedFields: string[];
  selectedSources: string[];
  selectedFrequencies: string[];
  selectedStates: string[];
  dateRange: { start: string; end: string };
  includeStale: boolean;
  includeInferredAvailability: boolean;
  viewMode: ViewMode;
  selectedEvidenceIds: string[];
  selectedFindingIds: string[];
  selectedChartPoints: Array<{ chart: string; index: number; x?: number; y?: number }>;

  // setters
  setActivePanel: (panelId: string | "latest") => void;
  setDecisionTime: (t: string) => void;
  setDecisionClock: (c: DecisionClock) => void;
  setSymbols: (s: string[]) => void;
  setDomains: (s: string[]) => void;
  setFields: (s: string[]) => void;
  setSources: (s: string[]) => void;
  setFrequencies: (s: string[]) => void;
  setStates: (s: string[]) => void;
  setDateRange: (r: { start: string; end: string }) => void;
  setIncludeStale: (b: boolean) => void;
  setIncludeInferredAvailability: (b: boolean) => void;
  setViewMode: (m: ViewMode) => void;
  setSelectedEvidence: (ids: string[]) => void;
  setSelectedFindings: (ids: string[]) => void;
  setChartPoint: (point: { chart: string; index: number; x?: number; y?: number } | null) => void;
}

export const useSliceStore = create<SliceState>((set) => ({
  activePanelId: "latest",
  decisionTime: new Date().toISOString(),
  decisionClock: "1805_ET",
  selectedSymbols: ["SPY", "QQQ", "GLD", "SLV"],
  selectedDomains: [],
  selectedFields: [],
  selectedSources: [],
  selectedFrequencies: [],
  selectedStates: [],
  dateRange: { start: "2026-01-01", end: "2026-07-21" },
  includeStale: false,
  includeInferredAvailability: false,
  viewMode: "research",
  selectedEvidenceIds: [],
  selectedFindingIds: [],
  selectedChartPoints: [],

  setActivePanel: (panelId) => set({ activePanelId: panelId }),
  setDecisionTime: (t) => set({ decisionTime: t }),
  setDecisionClock: (c) => set({ decisionClock: c }),
  setSymbols: (s) => set({ selectedSymbols: s }),
  setDomains: (s) => set({ selectedDomains: s }),
  setFields: (s) => set({ selectedFields: s }),
  setSources: (s) => set({ selectedSources: s }),
  setFrequencies: (s) => set({ selectedFrequencies: s }),
  setStates: (s) => set({ selectedStates: s }),
  setDateRange: (r) => set({ dateRange: r }),
  setIncludeStale: (b) => set({ includeStale: b }),
  setIncludeInferredAvailability: (b) => set({ includeInferredAvailability: b }),
  setViewMode: (m) => set({ viewMode: m }),
  setSelectedEvidence: (ids) => set({ selectedEvidenceIds: ids }),
  setSelectedFindings: (ids) => set({ selectedFindingIds: ids }),
  setChartPoint: (point) =>
    set({
      selectedChartPoints: point ? [point] : [],
    }),
}));
