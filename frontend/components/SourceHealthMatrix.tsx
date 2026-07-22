"use client";

// SourceHealthMatrix — source × field freshness grid (PRD §SourceHealthMatrix).
// Cell color: 🟢 fresh / 🟡 mid / 🔴 stale or failed.
// Hard rule: at least 1 stale/FAILED must show red (no silent hiding).

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { fetchSourceHealth, fetchMetrics } from "../lib/api";
import { dataAgeHuman, formatTimestamp, qualityPill } from "../lib/formatting";
import type { SourceHealthEntry } from "../types/api";

const P0_SOURCES = ["yfinance", "fred_alfred", "cftc_cot", "finra_regsho"];
const P1_SOURCES = ["finra_otc", "cboe_cfe", "sec_edgar", "etf_shares"];

export function SourceHealthMatrix() {
  const healthQ = useQuery({ queryKey: ["source-health"], queryFn: () => fetchSourceHealth(), refetchInterval: 30_000 });
  const metricsQ = useQuery({ queryKey: ["metrics-registry"], queryFn: () => fetchMetrics(), staleTime: 5 * 60_000 });

  const entries = healthQ.data?.sources ?? [];
  const bySource = useMemo(() => {
    const m = new Map<string, SourceHealthEntry>();
    for (const e of entries) m.set(e.source_id, e);
    return m;
  }, [entries]);

  const staleCount = entries.filter((e) => e.status === "STALE" || e.status === "FAILED").length;
  const fieldNames = (metricsQ.data ?? []).slice(0, 8).map((m) => m.field_name);

  return (
    <div className="card overflow-hidden">
      <header className="px-4 py-2 border-b border-ink-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-900">Source Health Matrix</h3>
        <div className="text-xs text-ink-500">
          {healthQ.data && `as_of ${formatTimestamp(healthQ.data.as_of_utc, false)}`}
        </div>
      </header>

      {staleCount > 0 && (
        <div className="px-4 py-2 bg-rose-50 border-b border-rose-200 text-xs text-rose-800">
          🔴 {staleCount} 个源数据非新鲜(可能影响结论置信度)。详见下方矩阵。
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-ink-50">
            <tr>
              <th className="text-left px-3 py-2 font-medium text-ink-700">源</th>
              <th className="text-left px-3 py-2 font-medium text-ink-700">状态</th>
              <th className="text-left px-3 py-2 font-medium text-ink-700">freshness</th>
              <th className="text-left px-3 py-2 font-medium text-ink-700">threshold</th>
              <th className="text-left px-3 py-2 font-medium text-ink-700">最后 ingest</th>
              <th className="text-left px-3 py-2 font-medium text-ink-700">quality</th>
            </tr>
          </thead>
          <tbody>
            {[...P0_SOURCES, ...P1_SOURCES].map((src) => {
              const e = bySource.get(src);
              const status = e?.status ?? "NO_DATA";
              const cell = cellFor(status);
              const pill = e ? qualityPill(e.last_quality) : qualityPill("EMPTY_RESPONSE");
              return (
                <tr key={src} className="border-t border-ink-200 hover:bg-ink-50">
                  <td className="px-3 py-2 font-mono text-ink-900">{src}</td>
                  <td className="px-3 py-2">
                    <span className={`quality-pill ${cell.bg} ${cell.text}`}>
                      <span className={`pulse-dot ${cell.dot}`} />
                      {status}
                    </span>
                  </td>
                  <td className="px-3 py-2 tabular-nums text-ink-700">
                    {e?.freshness_min !== null && e?.freshness_min !== undefined
                      ? `${e.freshness_min.toFixed(0)} min`
                      : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-ink-500">
                    {e?.threshold_min ? `${e.threshold_min} min` : "—"}
                  </td>
                  <td className="px-3 py-2 text-ink-700">
                    {e?.last_ingest_utc ? dataAgeHuman(e.last_ingest_utc) : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <span className={pill.className}>
                      <span className={`pulse-dot ${pill.dotClass}`} />
                      {pill.label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="px-4 py-2 text-xs text-ink-500 border-t border-ink-200">
        P0 关键源 4 个 · P1 增强源 4 个 ·{" "}
        <span className="text-ink-700">字段覆盖</span>: {fieldNames.length}/{(metricsQ.data ?? []).length} ({fieldNames.slice(0, 3).join(", ")}…)
      </div>
    </div>
  );
}

function cellFor(status: string): { bg: string; text: string; dot: string } {
  switch (status) {
    case "OK":        return { bg: "bg-emerald-50", text: "text-emerald-700", dot: "bg-emerald-500" };
    case "STALE":     return { bg: "bg-amber-50",   text: "text-amber-700",   dot: "bg-amber-500" };
    case "FAILED":    return { bg: "bg-rose-50",     text: "text-rose-700",    dot: "bg-rose-500" };
    case "THROTTLED": return { bg: "bg-orange-50",   text: "text-orange-700",  dot: "bg-orange-500" };
    default:          return { bg: "bg-ink-100",     text: "text-ink-600",     dot: "bg-ink-400" };
  }
}
