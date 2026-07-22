// selectionStore — cross-chart linking (PRD §全局状态设计).
// Holds: selected points from charts, brushed time ranges, selected cells
// from heatmap. Other components subscribe to react.

"use client";

import { create } from "zustand";

export interface ChartPoint {
  chartId: string;
  canonical_symbol?: string;
  field_name?: string;
  timestamp?: string;
  x?: number;
  y?: number;
  z_score?: number | null;
}

export interface TimeRange {
  start: string;
  end: string;
}

export interface SelectionState {
  // Hovered (highlight, not filter) — single point
  hoveredPoint: ChartPoint | null;
  // Clicked / brushed (filter) — array
  selectedPoints: ChartPoint[];
  // Brushed time range from any chart
  timeRange: TimeRange | null;
  // Heatmap cell click
  cellSelection: { symbol: string; domain: string } | null;
  // Evidence / Finding / Raw drawer IDs
  openEvidenceIds: string[];
  openFindingId: string | null;
  openRawHash: string | null;
  // Setters
  setHoveredPoint: (p: ChartPoint | null) => void;
  setSelectedPoints: (p: ChartPoint[]) => void;
  togglePoint: (p: ChartPoint) => void;
  setTimeRange: (r: TimeRange | null) => void;
  setCellSelection: (c: { symbol: string; domain: string } | null) => void;
  openEvidence: (id: string) => void;
  closeEvidence: () => void;
  setOpenFinding: (id: string | null) => void;
  setOpenRawHash: (h: string | null) => void;
  clearAll: () => void;
}

export const useSelectionStore = create<SelectionState>((set, get) => ({
  hoveredPoint: null,
  selectedPoints: [],
  timeRange: null,
  cellSelection: null,
  openEvidenceIds: [],
  openFindingId: null,
  openRawHash: null,

  setHoveredPoint: (p) => set({ hoveredPoint: p }),
  setSelectedPoints: (p) => set({ selectedPoints: p }),
  togglePoint: (p) => {
    const cur = get().selectedPoints;
    const idx = cur.findIndex(
      (x) => x.chartId === p.chartId && x.timestamp === p.timestamp && x.field_name === p.field_name,
    );
    if (idx >= 0) set({ selectedPoints: cur.filter((_, i) => i !== idx) });
    else set({ selectedPoints: [...cur, p] });
  },
  setTimeRange: (r) => set({ timeRange: r }),
  setCellSelection: (c) => set({ cellSelection: c }),
  openEvidence: (id) =>
    set({ openEvidenceIds: [id] }),
  closeEvidence: () => set({ openEvidenceIds: [] }),
  setOpenFinding: (id) => set({ openFindingId: id }),
  setOpenRawHash: (h) => set({ openRawHash: h }),
  clearAll: () =>
    set({
      hoveredPoint: null,
      selectedPoints: [],
      timeRange: null,
      cellSelection: null,
      openEvidenceIds: [],
      openFindingId: null,
      openRawHash: null,
    }),
}));
