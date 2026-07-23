"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchSystemHealth,
  fetchSystemTasks,
  cancelTask,
  triggerSync,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";

export default function SystemPage() {
  const qc = useQueryClient();

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: queryKeys.systemHealth(),
    queryFn: fetchSystemHealth,
    staleTime: 15_000,
    refetchInterval: 10_000,
  });

  const { data: tasks } = useQuery({
    queryKey: queryKeys.tasks(),
    queryFn: fetchSystemTasks,
    staleTime: 10_000,
    refetchInterval: 5_000,
  });

  const handleSync = async () => {
    const result = await triggerSync({});
    if (result) {
      alert(`同步任务已提交: ${result.job_id}`);
      qc.invalidateQueries({ queryKey: queryKeys.tasks() });
    }
  };

  const handleCancel = async (jobId: string) => {
    await cancelTask(jobId);
    qc.invalidateQueries({ queryKey: queryKeys.tasks() });
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-ink-900">系统健康</h1>
          <p className="text-sm text-ink-500 mt-1">
            监控系统状态、管理后台任务和触发数据同步
          </p>
        </div>
        <button className="btn-primary" onClick={handleSync}>
          触发同步
        </button>
      </div>

      {/* Health overview */}
      {healthLoading ? (
        <div className="card-pad text-center py-8 mb-6">
          <div className="skeleton h-4 w-40 mx-auto" />
        </div>
      ) : health ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <HealthCard
            label="系统状态"
            value={health.status}
            color={health.status === "ok" ? "emerald" : "amber"}
          />
          <HealthCard label="版本" value={health.version} />
          <HealthCard label="存储后端" value={health.storage_backend ?? "polars"} />
          <HealthCard label="DuckDB" value={health.duckdb_version ?? "N/A"} />
          <HealthCard label="面板数" value={health.panel_count?.toString() ?? "—"} />
          <HealthCard label="观测数" value={health.observation_count?.toString() ?? "—"} />
          <HealthCard
            label="运行时间"
            value={health.uptime_seconds ? `${Math.floor(health.uptime_seconds / 3600)}h` : "—"}
          />
          <HealthCard
            label="数据源"
            value={health.sources ? Object.keys(health.sources).length.toString() : "—"}
          />
        </div>
      ) : (
        <div className="card-pad text-center py-8 mb-6">
          <p className="text-sm text-ink-500">无法连接后端</p>
        </div>
      )}

      {/* Sources detail */}
      {health?.sources && Object.keys(health.sources).length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-ink-700 mb-3">数据源状态</h2>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-ink-50 border-b border-ink-200">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium text-ink-500">Source</th>
                  <th className="text-left px-4 py-2.5 font-medium text-ink-500">状态</th>
                  <th className="text-left px-4 py-2.5 font-medium text-ink-500">最后抓取</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(health.sources).map(([name, info]: [string, any]) => (
                  <tr key={name} className="border-b border-ink-100 hover:bg-ink-50">
                    <td className="px-4 py-2.5 font-mono text-xs">{name}</td>
                    <td className="px-4 py-2.5">
                      <span className={`quality-pill ${
                        info.status === "OK" ? "bg-emerald-100 text-emerald-700" :
                        info.status === "STALE" ? "bg-amber-100 text-amber-700" :
                        "bg-rose-100 text-rose-700"
                      }`}>
                        {info.status ?? "UNKNOWN"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-ink-500">
                      {info.last_ingest_utc ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Active tasks */}
      <h2 className="text-sm font-semibold text-ink-700 mb-3">后台任务</h2>
      {!tasks?.length ? (
        <div className="card-pad text-center py-8">
          <p className="text-sm text-ink-500">暂无活跃任务</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50 border-b border-ink-200">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">Job ID</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">类型</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">状态</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">进度</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">消息</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.job_id} className="border-b border-ink-100 hover:bg-ink-50">
                  <td className="px-4 py-2.5 font-mono text-xs">{t.job_id}</td>
                  <td className="px-4 py-2.5 text-xs">{t.task_type}</td>
                  <td className="px-4 py-2.5">
                    <span className={`quality-pill ${
                      t.status === "done" ? "bg-emerald-100 text-emerald-700" :
                      t.status === "failed" ? "bg-rose-100 text-rose-700" :
                      t.status === "running" ? "bg-blue-100 text-blue-700" :
                      "bg-amber-100 text-amber-700"
                    }`}>
                      {t.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums text-xs">{t.progress ?? 0}%</td>
                  <td className="px-4 py-2.5 text-xs text-ink-500 truncate max-w-xs">
                    {t.message ?? t.error ?? "—"}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {(t.status === "running" || t.status === "queued") && (
                      <button
                        className="text-rose-600 text-xs hover:underline"
                        onClick={() => handleCancel(t.job_id)}
                      >
                        取消
                      </button>
                    )}
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

function HealthCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: "emerald" | "amber" | "rose";
}) {
  const textColor =
    color === "emerald" ? "text-emerald-700" :
    color === "amber" ? "text-amber-700" :
    color === "rose" ? "text-rose-700" :
    "text-ink-900";
  return (
    <div className="card-pad">
      <p className="label-muted">{label}</p>
      <p className={`label-value mt-1 ${textColor}`}>{value}</p>
    </div>
  );
}
