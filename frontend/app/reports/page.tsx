"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchReports, triggerReportBuild, fetchPanels } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";

export default function ReportsPage() {
  const [panelId, setPanelId] = useState("");
  const [language, setLanguage] = useState("zh");
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();

  const { data: reports, isLoading } = useQuery({
    queryKey: queryKeys.reports(),
    queryFn: fetchReports,
    staleTime: 30_000,
  });

  const { data: panels } = useQuery({
    queryKey: queryKeys.panels(),
    queryFn: fetchPanels,
    staleTime: 60_000,
  });

  const handleBuild = async () => {
    setSubmitting(true);
    const result = await triggerReportBuild({
      panel_id: panelId || undefined,
      language,
    });
    setSubmitting(false);
    if (result) {
      alert(`报告生成任务已提交: ${result.job_id}`);
      qc.invalidateQueries({ queryKey: queryKeys.tasks() });
    }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-bold text-ink-900">报告生成</h1>
        <p className="text-sm text-ink-500 mt-1">
          基于 PIT 面板数据生成 LLM 分析报告，支持中英文
        </p>
      </div>

      <div className="card-pad mb-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="label-muted block mb-1.5">选择面板 (可选)</label>
            <select className="input" value={panelId} onChange={(e) => setPanelId(e.target.value)}>
              <option value="">全部面板</option>
              {panels?.map((p) => (
                <option key={p.panel_id} value={p.panel_id}>
                  {p.panel_id}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label-muted block mb-1.5">报告语言</label>
            <select className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </div>

          <div className="flex items-end">
            <button className="btn-primary w-full" onClick={handleBuild} disabled={submitting}>
              {submitting ? "生成中..." : "生成报告"}
            </button>
          </div>
        </div>
      </div>

      <h2 className="text-sm font-semibold text-ink-700 mb-3">历史报告</h2>

      {isLoading ? (
        <div className="card-pad text-center py-8">
          <div className="skeleton h-4 w-40 mx-auto mb-2" />
          <div className="skeleton h-3 w-28 mx-auto" />
        </div>
      ) : !reports?.length ? (
        <div className="card-pad text-center py-8">
          <p className="text-sm text-ink-500">暂无报告</p>
          <p className="text-xs text-ink-400 mt-1">点击上方按钮生成第一份报告</p>
        </div>
      ) : (
        <div className="space-y-3">
          {reports.map((r: any, i: number) => (
            <div key={r.report_id ?? i} className="card-pad flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-ink-900">
                  {r.title ?? `报告 ${r.report_id ?? i + 1}`}
                </p>
                <p className="text-xs text-ink-500 mt-0.5">
                  {r.created_at ?? "未知时间"} · {r.panel_id ?? "全量"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className={`quality-pill ${
                  r.status === "done" ? "bg-emerald-100 text-emerald-700" :
                  r.status === "failed" ? "bg-rose-100 text-rose-700" :
                  "bg-amber-100 text-amber-700"
                }`}>
                  {r.status ?? "unknown"}
                </span>
                {r.report_id && (
                  <a
                    href={`/reports/${encodeURIComponent(r.report_id)}`}
                    className="text-brand-600 hover:text-brand-700 text-xs font-medium"
                  >
                    查看 →
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
