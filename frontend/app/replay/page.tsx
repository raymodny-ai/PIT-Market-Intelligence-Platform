"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchPanels, fetchSnapshots } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import type { SnapshotDate } from "../../types/api";

export default function ReplayPage() {
  const [selectedPanel, setSelectedPanel] = useState<string>("");
  const [selectedDate, setSelectedDate] = useState<string>("");

  const { data: panels } = useQuery({
    queryKey: queryKeys.panels(),
    queryFn: fetchPanels,
    staleTime: 60_000,
  });

  const { data: snapshots, isLoading: snapLoading } = useQuery({
    queryKey: queryKeys.snapshots(selectedPanel),
    queryFn: () => fetchSnapshots(selectedPanel),
    enabled: !!selectedPanel,
    staleTime: 60_000,
  });

  const handleReplay = () => {
    if (!selectedPanel || !selectedDate) return;
    window.open(`/panels/${encodeURIComponent(selectedPanel)}?date=${selectedDate}`, "_blank");
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-bold text-ink-900">历史 Replay</h1>
        <p className="text-sm text-ink-500 mt-1">
          浏览面板历史快照，选择特定日期进行 Point-in-Time 回放
        </p>
      </div>

      <div className="card-pad mb-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="label-muted block mb-1.5">选择面板</label>
            <select
              className="input"
              value={selectedPanel}
              onChange={(e) => {
                setSelectedPanel(e.target.value);
                setSelectedDate("");
              }}
            >
              <option value="">— 请选择 —</option>
              {panels?.map((p) => (
                <option key={p.panel_id} value={p.panel_id}>
                  {p.panel_id} ({p.decision_time})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label-muted block mb-1.5">快照日期</label>
            <select
              className="input"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              disabled={!selectedPanel}
            >
              <option value="">— 请选择 —</option>
              {snapshots?.map((s: SnapshotDate) => (
                <option key={s.date} value={s.date}>
                  {s.date} ({s.row_count} rows)
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-end">
            <button
              className="btn-primary w-full"
              onClick={handleReplay}
              disabled={!selectedPanel || !selectedDate}
            >
              开始回放
            </button>
          </div>
        </div>
      </div>

      {snapLoading && selectedPanel && (
        <div className="card-pad text-center py-8">
          <div className="skeleton h-4 w-40 mx-auto mb-2" />
          <div className="skeleton h-3 w-28 mx-auto" />
        </div>
      )}

      {snapshots && snapshots.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-ink-200 bg-ink-50">
            <h3 className="text-sm font-medium text-ink-700">
              快照时间线 — {selectedPanel}
            </h3>
          </div>
          <div className="divide-y divide-ink-100">
            {snapshots.map((s: SnapshotDate) => (
              <div
                key={s.date}
                className={`px-4 py-3 flex items-center justify-between hover:bg-ink-50 cursor-pointer ${
                  selectedDate === s.date ? "bg-brand-50" : ""
                }`}
                onClick={() => setSelectedDate(s.date)}
              >
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${
                    selectedDate === s.date ? "bg-brand-600" : "bg-ink-300"
                  }`} />
                  <span className="text-sm font-mono">{s.date}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-ink-500 tabular-nums">{s.row_count} rows</span>
                  {s.quality_score != null && (
                    <span className="text-xs text-ink-500">
                      score: {s.quality_score.toFixed(2)}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {selectedPanel && snapshots?.length === 0 && !snapLoading && (
        <div className="card-pad text-center py-8">
          <p className="text-sm text-ink-500">该面板暂无历史快照</p>
        </div>
      )}
    </div>
  );
}
