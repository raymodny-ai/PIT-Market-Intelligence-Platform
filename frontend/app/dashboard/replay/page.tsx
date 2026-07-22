"use client";

// /dashboard/replay — historical decision time replay
// (PRD §URL 即状态 + §时间回放). Slider / input let the user pick a
// past decision_time; everything else (FilterRail, slice query, charts)
// reuses the same PIT logic as /dashboard.

import { useEffect, useState } from "react";
import { ErrorBoundary } from "../../../components/ErrorBoundary";
import { PITContextBar } from "../../../components/PITContextBar";
import { FilterRail } from "../../../components/FilterRail";
import { TimeSeriesChart } from "../../../components/TimeSeriesChart";
import { EmptyState } from "../../../components/EmptyState";
import { useSliceStore } from "../../../stores/sliceStore";
import { fetchPanel, fetchSlice, fetchPanelLatest } from "../../../lib/api";
import { formatTimestamp } from "../../../lib/formatting";

export default function ReplayPage() {
  const slice = useSliceStore();
  const [replayTime, setReplayTime] = useState(slice.decisionTime);
  const [replayClock, setReplayClock] = useState<"1605_ET" | "1805_ET">(slice.decisionClock);

  // Push replay state into store so charts react
  useEffect(() => {
    slice.setDecisionTime(replayTime);
    slice.setDecisionClock(replayClock);
  }, [replayTime, replayClock, slice]);

  const panelQ = useQueryLite();
  const sliceQ = useQueryLite();

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-ink-50">
        <PITContextBar
          panelId={panelQ.panelId}
          decisionTime={replayTime}
          panelVersion={panelQ.version}
          qualityStatus={panelQ.quality}
        />
        <div className="flex">
          <FilterRail />
          <main className="flex-1 p-4 space-y-4">
            <div className="card-pad">
              <h2 className="text-sm font-semibold text-ink-900 mb-3">历史时点回放</h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="label-muted block mb-1">decision_time</label>
                  <input
                    type="datetime-local"
                    value={replayTime.slice(0, 16)}
                    onChange={(e) => setReplayTime(new Date(e.target.value).toISOString())}
                    className="input"
                  />
                </div>
                <div>
                  <label className="label-muted block mb-1">decision_clock</label>
                  <div className="flex gap-1">
                    {(["1605_ET", "1805_ET"] as const).map((c) => (
                      <button
                        key={c}
                        type="button"
                        onClick={() => setReplayClock(c)}
                        className={`text-xs px-3 py-1.5 rounded border ${
                          replayClock === c
                            ? "bg-brand-50 border-brand-500 text-brand-700"
                            : "bg-white border-ink-200 text-ink-500"
                        }`}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="label-muted block mb-1">快捷选择</label>
                  <div className="flex gap-1 flex-wrap">
                    {[-7, -30, -90, -180, -365].map((days) => (
                      <button
                        key={days}
                        type="button"
                        className="btn-ghost text-xs"
                        onClick={() => {
                          const d = new Date(Date.now() + days * 24 * 3600 * 1000);
                          setReplayTime(d.toISOString());
                        }}
                      >
                        {Math.abs(days)}d ago
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="mt-3 text-xs text-ink-500">
                当前回放至:<span className="font-mono ml-1">{formatTimestamp(replayTime, false)}</span>
                {" "}({replayClock})。所有图表、Filter、AG Grid 在该时点重建。
              </div>
            </div>

            {sliceQ.data?.series?.length ? (
              <TimeSeriesChart series={sliceQ.data.series} title={`时序 · ${replayTime.slice(0, 10)}`} height={400} />
            ) : (
              <div className="card h-[420px] flex items-center justify-center">
                <EmptyState
                  variant="no-data"
                  title="回放时点尚无 PIT 数据"
                  description="选择更早的决策时点,或先到 /dashboard 跑一次 pit build"
                />
              </div>
            )}
          </main>
        </div>
      </div>
    </ErrorBoundary>
  );
}

// Tiny inline hooks to avoid a separate file import tangle
function useQueryLite() {
  // Local wrapper: re-uses slice & fetches
  // We import @tanstack/react-query lazily to keep this file simple
  // (the real one is in DashboardClient).
  const slice = useSliceStore();
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await (slice.panelId === "latest" ? fetchPanelLatest() : fetchPanel(slice.panelId));
        if (cancelled) return;
        setData(p);
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, [slice.panelId]);
  const [sliceData, setSliceData] = useState<any>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!data?.panel_id || data.panel_id === "latest") { setSliceData(null); return; }
      try {
        const s = await fetchSlice({
          panel_id: data.panel_id,
          decision_time: slice.decisionTime,
          decision_clock: slice.decisionClock,
          symbols: slice.symbols,
          start: slice.dateRange.start,
          end: slice.dateRange.end,
        });
        if (cancelled) return;
        setSliceData(s);
      } catch { setSliceData(null); }
    })();
    return () => { cancelled = true; };
  }, [data?.panel_id, slice.decisionTime, slice.decisionClock, slice.symbols.join(","), slice.dateRange.start, slice.dateRange.end]);
  return { panelId: data?.panel_id, version: data?.panel_version, quality: data?.quality_status, data: sliceData };
}
