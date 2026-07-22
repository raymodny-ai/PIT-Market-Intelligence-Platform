"use client";

// /reports/[reportId] — frozen report (PRD §页面路由 /reports/[reportId]).
// Immutable; lists LLM findings + evidence ids; can export as JSON.

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ErrorBoundary } from "../../../components/ErrorBoundary";
import { PITContextBar } from "../../../components/PITContextBar";
import { FilterRail } from "../../../components/FilterRail";
import { FindingCard } from "../../../components/FindingCard";
import { EvidenceDrawer } from "../../../components/EvidenceDrawer";
import { LineageDrawer } from "../../../components/LineageDrawer";
import { EmptyState } from "../../../components/EmptyState";
import { useSelectionStore } from "../../../stores/selectionStore";
import { useSliceStore } from "../../../stores/sliceStore";
import { fetchEvidence } from "../../../lib/api";
import { formatTimestamp, dataAgeHuman } from "../../../lib/formatting";
import type { Finding } from "../../../types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

interface FrozenReport {
  report_id: string;
  title: string;
  panel_id: string;
  frozen: boolean;
  frozen_at_utc: string;
  finding_count: number;
  findings?: Finding[];
}

export default function ReportPage() {
  const params = useParams<{ reportId: string }>();
  const reportId = params?.reportId ?? "sample";
  const slice = useSliceStore();
  const openRawHash = useSelectionStore((s) => s.openRawHash);

  // Frozen reports live as JSON files at data/gold/reports/{report_id}.json
  // (per T-32). The backend's /v1/reports/{id} endpoint would surface them.
  // For the demo path we use /v1/analyses/evidence/{panel} as fallback.
  const [report, setReport] = useState<FrozenReport | null>(null);
  const [loading, setLoading] = useState(true);

  // Try fetching from API; fall back to placeholder
  useState(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/v1/reports/${encodeURIComponent(reportId)}`);
        if (r.ok) {
          const j = await r.json();
          setReport(j);
        } else {
          setReport({
            report_id: reportId,
            title: `Sample Report ${reportId}`,
            panel_id: "latest",
            frozen: true,
            frozen_at_utc: new Date().toISOString(),
            finding_count: 0,
          });
        }
      } catch {
        setReport({
          report_id: reportId,
          title: `Sample Report ${reportId}`,
          panel_id: "latest",
          frozen: true,
          frozen_at_utc: new Date().toISOString(),
          finding_count: 0,
        });
      } finally {
        setLoading(false);
      }
    })();
  });

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-ink-50">
        <PITContextBar
          panelId={report?.panel_id ?? "—"}
          decisionTime={report?.frozen_at_utc ?? slice.decisionTime}
          panelVersion="frozen"
        />
        <div className="flex">
          <FilterRail />
          <main className="flex-1 min-w-0 p-4 space-y-4">
            <div className="card-pad">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-ink-500">冻结报告</div>
                  <h1 className="text-xl font-bold text-ink-900 mt-1">{report?.title ?? reportId}</h1>
                  <div className="mt-1 text-xs text-ink-500 flex gap-3">
                    <span>report_id: <span className="font-mono text-ink-700">{reportId}</span></span>
                    <span>panel: <span className="font-mono text-ink-700">{report?.panel_id ?? "—"}</span></span>
                    <span>冻结: {report ? formatTimestamp(report.frozen_at_utc, false) : "—"}</span>
                    <span>age: {report ? dataAgeHuman(report.frozen_at_utc) : "—"}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {report?.frozen && (
                    <span className="quality-pill bg-ink-100 text-ink-700">🔒 不可变</span>
                  )}
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => exportReportJson(report)}
                    disabled={!report}
                  >
                    导出 JSON
                  </button>
                </div>
              </div>
            </div>

            {loading ? (
              <div className="card p-4 h-32 skeleton" />
            ) : (report?.findings?.length ?? 0) > 0 ? (
              <section>
                <h2 className="text-sm font-semibold text-ink-900 mb-2">
                  LLM Findings ({report!.findings!.length})
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {report!.findings!.map((f) => <FindingCard key={f.finding_id} finding={f} />)}
                </div>
              </section>
            ) : (
              <div className="card h-[200px] flex items-center justify-center">
                <EmptyState
                  variant="no-data"
                  title="该报告暂无 LLM Finding"
                  description="使用 pit-market CLI: pit-market analyze + report build"
                />
              </div>
            )}
          </main>
        </div>
        {report?.panel_id && <EvidenceDrawer panelId={report.panel_id} />}
        {openRawHash && <LineageDrawer defaultEntityId={openRawHash} />}
      </div>
    </ErrorBoundary>
  );
}

function exportReportJson(r: FrozenReport | null) {
  if (!r) return;
  const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${r.report_id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}
