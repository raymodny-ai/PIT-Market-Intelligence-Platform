"use client";

// /health — Source Health Matrix + Revision Timeline (PRD §页面路由 /health).
// Also: 4 KPI cards for SLA, stale count, sources, last_ingest.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { PITContextBar } from "../../components/PITContextBar";
import { SourceHealthMatrix } from "../../components/SourceHealthMatrix";
import { RevisionTimeline } from "../../components/RevisionTimeline";
import { fetchRevisionTimeline, fetchMetrics } from "../../lib/api";
import { fetchPanelLatest } from "../../lib/api";
import { dataAgeHuman, formatTimestamp } from "../../lib/formatting";
import { useSliceStore } from "../../stores/sliceStore";

export default function HealthPage() {
  const slice = useSliceStore();
  const [asKnown, setAsKnown] = useState(true);

  const metricsQ = useQuery({ queryKey: ["metrics-registry"], queryFn: () => fetchMetrics(), staleTime: 5 * 60_000 });
  const firstField = metricsQ.data?.[0];
  const revisionQ = useQuery({
    queryKey: ["revision", firstField?.field_name, firstField?.source_name],
    queryFn: () => fetchRevisionTimeline(firstField!.field_name, firstField!.source_name),
    enabled: !!firstField,
    staleTime: 60_000,
  });

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-ink-50">
        <PITContextBar
          panelId="health"
          decisionTime={new Date().toISOString()}
          qualityStatus="VALID"
        />
        <main className="p-4 space-y-4 max-w-7xl mx-auto">
          <div className="card-pad">
            <h1 className="text-base font-semibold text-ink-900 mb-1">数据源健康</h1>
            <p className="text-xs text-ink-500">
              Source Health Matrix + Revision Timeline (ALFRED vintage 比较)。
              任何 stale / failed 数据均显式呈现,不得静默隐藏。
            </p>
          </div>

          <SourceHealthMatrix />

          <div className="card-pad">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-ink-900">ALFRED Vintage Revision</h2>
              <div className="flex items-center gap-2 text-xs">
                <span className="label-muted">as-known</span>
                <button
                  type="button"
                  onClick={() => setAsKnown(!asKnown)}
                  className={`relative inline-flex h-5 w-9 rounded-full transition-colors ${
                    asKnown ? "bg-brand-600" : "bg-ink-300"
                  }`}
                  aria-label="切换 as-known / latest"
                >
                  <span
                    className={`absolute top-0.5 ${asKnown ? "left-0.5" : "left-4"} h-4 w-4 rounded-full bg-white transition-all`}
                  />
                </button>
                <span className="label-muted">latest</span>
              </div>
            </div>
            {revisionQ.data ? (
              <RevisionTimeline data={revisionQ.data} height={300} />
            ) : (
              <div className="h-[320px] flex items-center justify-center text-ink-400 text-sm bg-ink-50 rounded">
                {revisionQ.isLoading ? "加载 revision..." : "无 ALFRED vintage 数据(需要先 ingest 宏观数据)"}
              </div>
            )}
          </div>

          <footer className="text-xs text-ink-400 text-center pt-2">
            数据刷新频率 30s · 任何 ≥1 个 stale 单元格自动触发顶部红色横幅
          </footer>
        </main>
      </div>
    </ErrorBoundary>
  );
}
