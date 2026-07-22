"use client";

// Dashboard — market overview workspace (PRD §页面路由 /dashboard).
// Layout: top PITContextBar + left FilterRail (240px) + main content
// (KPI cards, risk heatmap, time-series chart, AG Grid table).
// URL ↔ sliceStore sync via useUrlState.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { PITContextBar } from "../../components/PITContextBar";
import { FilterRail } from "../../components/FilterRail";
import { TimeSeriesChart } from "../../components/TimeSeriesChart";
import { RiskHeatmap } from "../../components/RiskHeatmap";
import { AGGridPanel } from "../../components/AGGridPanel";
import { EvidenceDrawer } from "../../components/EvidenceDrawer";
import { LineageDrawer } from "../../components/LineageDrawer";
import { SSEProgressBar } from "../../components/SSEProgressBar";
import { EmptyState } from "../../components/EmptyState";
import { FindingCard } from "../../components/FindingCard";
import { useUrlState } from "../../lib/useUrlState";
import { useSliceStore } from "../../stores/sliceStore";
import { useReportStore } from "../../stores/reportStore";
import { useSelectionStore } from "../../stores/selectionStore";
import {
  fetchPanelLatest,
  fetchPanel,
  fetchSlice,
  fetchHeatmap,
  fetchFinding,
} from "../../lib/api";
import { formatNumber, qualityPill, dataAgeHuman } from "../../lib/formatting";
import type { Finding } from "../../types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export default function DashboardClient() {
  useUrlState();
  const router = useRouter();
  const slice = useSliceStore();
  const openRawHash = useSelectionStore((s) => s.openRawHash);
  const startRun = useReportStore((s) => s.startRun);

  const panelQuery = useQuery({
    queryKey: ["panel-latest", slice.panelId],
    queryFn: () => slice.panelId === "latest" ? fetchPanelLatest() : fetchPanel(slice.panelId),
    staleTime: 30_000,
  });

  const panelId = panelQuery.data?.panel_id ?? slice.panelId;
  const effectivePanelId = panelId && panelId !== "latest" ? panelId : null;

  const sliceQ = useQuery({
    queryKey: ["slice", effectivePanelId, slice.decisionTime, slice.symbols.join(",")],
    queryFn: () => fetchSlice({
      panel_id: effectivePanelId!,
      decision_time: slice.decisionTime,
      decision_clock: slice.decisionClock,
      symbols: slice.symbols,
      start: slice.dateRange.start,
      end: slice.dateRange.end,
    }),
    enabled: !!effectivePanelId,
    staleTime: 30_000,
  });

  const heatmapQ = useQuery({
    queryKey: ["heatmap", effectivePanelId, slice.symbols.join(",")],
    queryFn: () => fetchHeatmap({ panel_id: effectivePanelId!, decision_time: slice.decisionTime, symbols: slice.symbols }),
    enabled: !!effectivePanelId,
    staleTime: 60_000,
  });

  const [demoFindings, setDemoFindings] = useState<Finding[]>([]);

  // Demo: load sample finding on first mount
  useEffect(() => {
    fetchFinding("sample").then((f) => { if (f) setDemoFindings([f]); });
  }, []);

  const handleAnalyze = async () => {
    if (!effectivePanelId) {
      // No panel resolved — redirect to /panels/latest so the user lands on a
      // real panel route. The switcher in PITContextBar is the persistent
      // way to pick a specific panel.
      router.push("/panels/latest");
      return;
    }
    try {
      const r = await fetch(`${API_BASE}/v1/analyses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ panel_id: effectivePanelId, provider: "mock" }),
      });
      if (!r.ok) {
        alert(`analyze 启动失败: ${r.status} ${r.statusText}`);
        return;
      }
      const data = await r.json();
      const runId = data.analysis_run_id ?? data.run_id;
      if (runId) startRun(runId, effectivePanelId);
    } catch (e: any) {
      alert(`analyze 错误: ${e.message}`);
    }
  };

  return (
    <div className="min-h-screen bg-ink-50">
      <PITContextBar
        panelId={panelQuery.data?.panel_id ?? slice.panelId}
        decisionTime={slice.decisionTime}
        panelVersion={panelQuery.data?.panel_version}
        featureVersion={panelQuery.data?.feature_version}
        qualityStatus={panelQuery.data?.quality_status}
        onSaveSnapshot={() => alert("另存为快照: TODO T-32 / 报告 API 已就绪,前端可调用 POST /v1/panels/{id}/report")}
      />

      <div className="flex">
        <FilterRail onAnalyzeClick={handleAnalyze} />

        <main className="flex-1 min-w-0 p-4 space-y-4">
          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Universe" value={slice.symbols.length.toString()} sub={slice.symbols.join(" · ")} />
            <KpiCard
              label="Decision Time"
              value={slice.decisionTime.slice(0, 10)}
              sub={`${slice.decisionClock} · age ${dataAgeHuman(slice.decisionTime)}`}
            />
            <KpiCard
              label="Quality"
              value={panelQuery.data?.quality_status ?? "—"}
              sub={panelQuery.data?.quality_score !== undefined ? `score ${panelQuery.data.quality_score.toFixed(2)}` : "no panel"}
              tone={panelQuery.data?.quality_status === "VALID" ? "ok" : "warn"}
            />
            <KpiCard
              label="Row count"
              value={panelQuery.data?.row_count?.toLocaleString() ?? "—"}
              sub={panelQuery.data?.field_count ? `${panelQuery.data.field_count} fields` : ""}
            />
          </div>

          {/* Risk heatmap + time series */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="lg:col-span-1">
              {heatmapQ.data ? (
                <RiskHeatmap data={heatmapQ.data} />
              ) : (
                <div className="card p-4 h-[400px] flex items-center justify-center text-ink-400 text-sm">
                  {heatmapQ.isLoading ? "加载热图..." : <EmptyState variant="no-data" title="暂无可视化热图数据" description="需要 panel 构建 + 数据 ingest 完成后显示" />}
                </div>
              )}
            </div>
            <div className="lg:col-span-2">
              {sliceQ.data?.series?.length ? (
                <TimeSeriesChart
                  series={sliceQ.data.series}
                  title="PIT 切片 · 多标的时序"
                  height={400}
                />
              ) : (
                <div className="card p-4 h-[400px] flex items-center justify-center text-ink-400 text-sm">
                  {sliceQ.isLoading ? "加载时序..." : <EmptyState variant="no-data" title="暂无 PIT 时序数据" description="后端 panel 构建后此处自动填充" />}
                </div>
              )}
            </div>
          </div>

          {/* AG Grid wide table */}
          {effectivePanelId ? (
            <AGGridPanel panelId={effectivePanelId} height={420} />
          ) : (
            <div className="card p-4 h-[200px] flex items-center justify-center text-ink-400 text-sm">
              <EmptyState
                variant="no-data"
                title="等待 panel 加载"
                description="Dashboard 默认使用 /v1/panels/latest,当前没有可用的 panel"
              />
            </div>
          )}

          {/* Demo findings */}
          {demoFindings.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-ink-900 mb-2">LLM Finding 样本</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {demoFindings.map((f) => <FindingCard key={f.finding_id} finding={f} />)}
              </div>
            </section>
          )}
        </main>
      </div>

      <EvidenceDrawer panelId={effectivePanelId ?? "latest"} />
      {openRawHash && <LineageDrawer defaultEntityId={openRawHash} />}
      <SSEProgressBar />
    </div>
  );
}

function KpiCard({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "ok" | "warn" }) {
  const pill = tone === "warn" ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700";
  return (
    <div className="card-pad">
      <div className="label-muted mb-1">{label}</div>
      <div className="text-xl font-bold text-ink-900 tabular-nums font-mono">{value}</div>
      {sub && <div className={`text-xs mt-1 ${tone === "warn" ? "text-amber-600" : "text-ink-500"} truncate`}>{sub}</div>}
    </div>
  );
}
