// reportStore — current report + SSE analysis state (PRD §全局状态设计).
// Drives SSEProgressBar and the analyze-button flow.

"use client";

import { create } from "zustand";
import type { AnalysisStage } from "../types/api";

export interface ReportSnapshot {
  report_id: string;
  panel_id: string;
  title: string;
  frozen: boolean;
  frozen_at_utc: string;
  finding_count: number;
}

export interface AnalysisRun {
  run_id: string;
  panel_id: string;
  stage: AnalysisStage;
  progress_pct: number;            // 0..100
  evidence_count?: number;
  model?: string;
  finding_count?: number;
  started_at_utc: string;
  last_event_id?: string;
  error?: string;
}

export interface ReportState {
  // Currently viewed report (frozen)
  currentReport: ReportSnapshot | null;
  // Active analysis run (in-flight SSE)
  currentRun: AnalysisRun | null;
  // Reconnect bookkeeping
  reconnectAttempts: number;
  setCurrentReport: (r: ReportSnapshot | null) => void;
  startRun: (run_id: string, panel_id: string) => void;
  updateRunStage: (stage: AnalysisStage, progress_pct: number, extras?: Partial<AnalysisRun>) => void;
  finishRun: (finding_count: number) => void;
  failRun: (error: string) => void;
  recordReconnect: () => void;
  clearRun: () => void;
}

const nowIso = () => new Date().toISOString();

export const useReportStore = create<ReportState>((set) => ({
  currentReport: null,
  currentRun: null,
  reconnectAttempts: 0,

  setCurrentReport: (r) => set({ currentReport: r }),

  startRun: (run_id, panel_id) =>
    set({
      currentRun: {
        run_id,
        panel_id,
        stage: "QUEUED",
        progress_pct: 0,
        started_at_utc: nowIso(),
      },
      reconnectAttempts: 0,
    }),

  updateRunStage: (stage, progress_pct, extras) =>
    set((s) =>
      s.currentRun
        ? { currentRun: { ...s.currentRun, stage, progress_pct, ...extras } }
        : s,
    ),

  finishRun: (finding_count) =>
    set((s) =>
      s.currentRun
        ? { currentRun: { ...s.currentRun, stage: "PUBLISHED", progress_pct: 100, finding_count } }
        : s,
    ),

  failRun: (error) =>
    set((s) =>
      s.currentRun
        ? { currentRun: { ...s.currentRun, stage: "REJECTED", error } }
        : s,
    ),

  recordReconnect: () => set((s) => ({ reconnectAttempts: s.reconnectAttempts + 1 })),

  clearRun: () => set({ currentRun: null, reconnectAttempts: 0 }),
}));
