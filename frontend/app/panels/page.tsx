"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchPanels, triggerPanelBuild, fetchSystemHealth } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import Link from "next/link";

export default function PanelsPage() {
  const { data: panels, isLoading } = useQuery({
    queryKey: queryKeys.panels(),
    queryFn: fetchPanels,
    staleTime: 60_000,
  });

  const { data: health } = useQuery({
    queryKey: queryKeys.systemHealth(),
    queryFn: fetchSystemHealth,
    staleTime: 30_000,
  });

  const handleBuild = async () => {
    const result = await triggerPanelBuild({});
    if (result) {
      alert(`构建任务已提交: ${result.job_id}`);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-ink-900">面板管理</h1>
          <p className="text-sm text-ink-500 mt-1">管理 PIT 面板、触发构建和查看历史快照</p>
        </div>
        <button onClick={handleBuild} className="btn-primary">
          触发构建
        </button>
      </div>

      {health && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="card-pad">
            <p className="label-muted">存储后端</p>
            <p className="label-value mt-1">{health.storage_backend ?? "polars"}</p>
          </div>
          <div className="card-pad">
            <p className="label-muted">面板总数</p>
            <p className="label-value mt-1">{health.panel_count ?? "—"}</p>
          </div>
          <div className="card-pad">
            <p className="label-muted">观测总数</p>
            <p className="label-value mt-1">{health.observation_count ?? "—"}</p>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="card-pad text-center py-12">
          <div className="skeleton h-4 w-48 mx-auto mb-2" />
          <div className="skeleton h-3 w-32 mx-auto" />
        </div>
      ) : !panels?.length ? (
        <div className="card-pad text-center py-12">
          <p className="text-sm text-ink-500">暂无面板数据</p>
          <p className="text-xs text-ink-400 mt-1">请先触发数据同步或面板构建</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50 border-b border-ink-200">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">Panel ID</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">决策时间</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">版本</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">质量</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">行数</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {panels.map((p) => (
                <tr key={p.panel_id} className="border-b border-ink-100 hover:bg-ink-50">
                  <td className="px-4 py-2.5 font-mono text-xs">{p.panel_id}</td>
                  <td className="px-4 py-2.5">{p.decision_time}</td>
                  <td className="px-4 py-2.5">{p.panel_version}</td>
                  <td className="px-4 py-2.5">
                    <span className={`quality-pill ${qualityColor(p.quality_status)}`}>
                      {p.quality_status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{p.row_count ?? "—"}</td>
                  <td className="px-4 py-2.5">
                    <Link
                      href={`/panels/${encodeURIComponent(p.panel_id)}`}
                      className="text-brand-600 hover:text-brand-700 text-xs font-medium"
                    >
                      详情 →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function qualityColor(s: string): string {
  switch (s) {
    case "VALID": return "bg-emerald-100 text-emerald-700";
    case "DEGRADED": return "bg-amber-100 text-amber-700";
    case "STALE": return "bg-orange-100 text-orange-700";
    case "REJECTED": return "bg-rose-100 text-rose-700";
    default: return "bg-ink-100 text-ink-600";
  }
}
