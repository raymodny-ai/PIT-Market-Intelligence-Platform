"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchRegistry,
  fetchPanels,
  exportCsvUrl,
  exportParquetUrl,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";

export default function RegistryPage() {
  const [tab, setTab] = useState<"instruments" | "metrics">("instruments");
  const [search, setSearch] = useState("");

  const { data: registry, isLoading } = useQuery({
    queryKey: queryKeys.registry(),
    queryFn: fetchRegistry,
    staleTime: 120_000,
  });

  const { data: panels } = useQuery({
    queryKey: queryKeys.panels(),
    queryFn: fetchPanels,
    staleTime: 60_000,
  });

  const items = tab === "instruments"
    ? registry?.instruments ?? []
    : registry?.metrics ?? [];

  const filtered = search
    ? items.filter(
        (i) =>
          i.name.toLowerCase().includes(search.toLowerCase()) ||
          (i.display_name_zh ?? "").includes(search)
      )
    : items;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-bold text-ink-900">注册表 & 数据导出</h1>
        <p className="text-sm text-ink-500 mt-1">
          浏览工具/指标注册表，导出面板数据为 CSV 或 Parquet
        </p>
      </div>

      {/* Export section */}
      <div className="card-pad mb-6">
        <h2 className="text-sm font-semibold text-ink-700 mb-3">数据导出</h2>
        <div className="flex flex-wrap gap-2">
          {panels?.map((p) => (
            <div key={p.panel_id} className="flex items-center gap-2 bg-ink-50 rounded px-3 py-1.5">
              <span className="text-xs font-mono text-ink-700">{p.panel_id}</span>
              <a
                href={exportCsvUrl(p.panel_id)}
                className="text-xs text-brand-600 hover:underline"
                download
              >
                CSV
              </a>
              <a
                href={exportParquetUrl(p.panel_id)}
                className="text-xs text-brand-600 hover:underline"
                download
              >
                Parquet
              </a>
            </div>
          ))}
          {!panels?.length && (
            <p className="text-xs text-ink-400">暂无可导出的面板</p>
          )}
        </div>
      </div>

      {/* Registry tabs */}
      <div className="flex gap-4 mb-4 border-b border-ink-200">
        <button
          className={`pb-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "instruments"
              ? "border-brand-600 text-brand-700"
              : "border-transparent text-ink-500 hover:text-ink-700"
          }`}
          onClick={() => setTab("instruments")}
        >
          工具 ({registry?.instruments.length ?? 0})
        </button>
        <button
          className={`pb-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "metrics"
              ? "border-brand-600 text-brand-700"
              : "border-transparent text-ink-500 hover:text-ink-700"
          }`}
          onClick={() => setTab("metrics")}
        >
          指标 ({registry?.metrics.length ?? 0})
        </button>
      </div>

      <div className="mb-4">
        <input
          className="input max-w-xs"
          placeholder="搜索名称..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {isLoading ? (
        <div className="card-pad text-center py-8">
          <div className="skeleton h-4 w-40 mx-auto" />
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50 border-b border-ink-200">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">名称</th>
                {tab === "instruments" ? (
                  <>
                    <th className="text-left px-4 py-2.5 font-medium text-ink-500">资产类别</th>
                    <th className="text-left px-4 py-2.5 font-medium text-ink-500">中文名</th>
                  </>
                ) : (
                  <>
                    <th className="text-left px-4 py-2.5 font-medium text-ink-500">数据源</th>
                    <th className="text-left px-4 py-2.5 font-medium text-ink-500">中文名</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.name} className="border-b border-ink-100 hover:bg-ink-50">
                  <td className="px-4 py-2.5 font-mono text-xs">{item.name}</td>
                  <td className="px-4 py-2.5 text-xs">
                    {tab === "instruments" ? item.asset_class : item.source ?? "—"}
                  </td>
                  <td className="px-4 py-2.5 text-xs">{item.display_name_zh ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="text-center py-6 text-sm text-ink-400">无匹配项</div>
          )}
        </div>
      )}
    </div>
  );
}
