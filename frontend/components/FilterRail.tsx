"use client";

// FilterRail — left fixed filter panel (PRD §FilterRail).
// 240px wide. All controls immediately update the sliceStore → URL.

import { useEffect, useState } from "react";
import {
  useSliceStore,
  DOMAINS,
  SOURCES,
  QUALITY_OPTIONS,
  FREQUENCIES,
  type DomainKey,
  type SourceKey,
  type QualityFilter,
  type Frequency,
} from "../stores/sliceStore";
import { useSelectionStore } from "../stores/selectionStore";
import { fetchInstruments, fetchSourceHealth } from "../lib/api";
import type { SourceHealthEntry } from "../types/api";

export interface FilterRailProps {
  onAnalyzeClick?: () => void;
  analyzeRunning?: boolean;
}

interface InstrumentLite {
  canonical_symbol: string;
  asset_class: string;
  display_name_zh?: string;
  display_name_en?: string;
}

const ASSET_LABELS: Record<string, string> = {
  equity_etf: "股票 ETF",
  commodity_etf: "商品 ETF",
  volatility: "波动率",
  bond_etf: "债券 ETF",
  fx: "外汇",
};

export function FilterRail({ onAnalyzeClick, analyzeRunning }: FilterRailProps) {
  const slice = useSliceStore();
  const cellSelection = useSelectionStore((s) => s.cellSelection);
  const setCellSelection = useSelectionStore((s) => s.setCellSelection);

  const [instruments, setInstruments] = useState<InstrumentLite[]>([]);
  const [health, setHealth] = useState<SourceHealthEntry[]>([]);

  useEffect(() => {
    fetchInstruments().then(setInstruments);
    fetchSourceHealth().then((m) => m && setHealth(m.sources));
  }, []);

  const grouped = groupBy(instruments, (i) => i.asset_class);

  return (
    <aside
      className="w-[240px] shrink-0 border-r border-ink-200 bg-white overflow-y-auto"
      style={{ height: "calc(100vh - 44px)" }}
    >
      {/* Symbols */}
      <Section title="标的" subtitle={`${slice.symbols.length} 选中`}>
        {Array.from(grouped.entries()).map(([cls, items]) => (
          <div key={cls} className="mb-3">
            <div className="label-muted mb-1">{ASSET_LABELS[cls] ?? cls}</div>
            <div className="space-y-0.5">
              {items.map((i) => (
                <label key={i.canonical_symbol} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-ink-50 px-1.5 py-0.5 rounded">
                  <input
                    type="checkbox"
                    checked={slice.symbols.includes(i.canonical_symbol)}
                    onChange={() => slice.toggleSymbol(i.canonical_symbol)}
                    className="rounded text-brand-600"
                  />
                  <span className="font-mono text-xs">{i.canonical_symbol}</span>
                  <span className="text-ink-500 text-xs truncate">
                    {i.display_name_zh ?? i.display_name_en ?? ""}
                  </span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </Section>

      {/* Date Range */}
      <Section title="时间范围">
        <div className="flex gap-1 mb-2 flex-wrap">
          {[
            { label: "1M", days: 30 },
            { label: "3M", days: 90 },
            { label: "6M", days: 180 },
            { label: "YTD", days: ytdDays() },
            { label: "1Y", days: 365 },
          ].map((p) => (
            <button
              key={p.label}
              type="button"
              onClick={() => {
                const end = new Date();
                const start = new Date(end.getTime() - p.days * 24 * 3600 * 1000);
                slice.setDateRange({
                  start: start.toISOString().slice(0, 10),
                  end: end.toISOString().slice(0, 10),
                });
              }}
              className="btn-ghost text-xs px-2 py-0.5"
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="space-y-1.5">
          <input
            type="date"
            value={slice.dateRange.start}
            onChange={(e) => slice.setDateRange({ ...slice.dateRange, start: e.target.value })}
            className="input"
          />
          <input
            type="date"
            value={slice.dateRange.end}
            onChange={(e) => slice.setDateRange({ ...slice.dateRange, end: e.target.value })}
            className="input"
          />
        </div>
        <div className="mt-2 flex gap-1">
          {(["1605_ET", "1805_ET"] as const).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => slice.setDecisionClock(c)}
              className={`text-xs px-2 py-0.5 rounded border ${
                slice.decisionClock === c
                  ? "bg-brand-50 border-brand-500 text-brand-700"
                  : "bg-white border-ink-200 text-ink-500 hover:border-ink-300"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </Section>

      {/* Domains */}
      <Section title="因子域">
        <div className="space-y-0.5">
          {DOMAINS.map((d) => (
            <label key={d.key} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-ink-50 px-1.5 py-0.5 rounded">
              <input
                type="checkbox"
                checked={slice.domains.includes(d.key as DomainKey)}
                onChange={() => slice.toggleDomain(d.key as DomainKey)}
                className="rounded text-brand-600"
              />
              <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: d.color }} />
              <span>{d.label}</span>
            </label>
          ))}
        </div>
      </Section>

      {/* Data Sources */}
      <Section title="数据源">
        <div className="space-y-0.5">
          {SOURCES.map((s) => {
            const h = health.find((x) => x.source_id === s.key);
            const statusColor =
              h?.status === "OK" ? "bg-emerald-500" :
              h?.status === "STALE" ? "bg-amber-500" :
              h?.status === "FAILED" ? "bg-red-500" :
              h?.status === "THROTTLED" ? "bg-orange-500" :
              "bg-gray-300";
            return (
              <label key={s.key} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-ink-50 px-1.5 py-0.5 rounded">
                <input
                  type="checkbox"
                  checked={slice.dataSources.includes(s.key as SourceKey)}
                  onChange={() => slice.toggleDataSource(s.key as SourceKey)}
                  className="rounded text-brand-600"
                />
                <span className={`w-1.5 h-1.5 rounded-full ${statusColor}`} />
                <span className="text-xs">{s.label}</span>
              </label>
            );
          })}
        </div>
      </Section>

      {/* Frequency */}
      <Section title="频率">
        <div className="flex gap-1">
          {FREQUENCIES.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => slice.setFrequency(f as Frequency)}
              className={`text-xs px-2 py-0.5 rounded border ${
                slice.frequency === f
                  ? "bg-brand-50 border-brand-500 text-brand-700"
                  : "bg-white border-ink-200 text-ink-500 hover:border-ink-300"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </Section>

      {/* Quality */}
      <Section title="质量过滤">
        <div className="space-y-0.5">
          {QUALITY_OPTIONS.map((q) => (
            <label key={q} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-ink-50 px-1.5 py-0.5 rounded">
              <input
                type="checkbox"
                checked={slice.qualityFilter.includes(q as QualityFilter)}
                onChange={() => slice.toggleQualityFilter(q as QualityFilter)}
                className="rounded text-brand-600"
              />
              <span className="text-xs">{q}</span>
            </label>
          ))}
        </div>
      </Section>

      {cellSelection && (
        <Section title="热图联动">
          <div className="text-xs bg-brand-50 border border-brand-200 rounded p-2">
            <div>标的: <b>{cellSelection.symbol}</b></div>
            <div>因子域: <b>{cellSelection.domain}</b></div>
            <button
              type="button"
              className="btn-ghost mt-2 text-xs"
              onClick={() => setCellSelection(null)}
            >
              清除
            </button>
          </div>
        </Section>
      )}

      {/* Analyze button */}
      <div className="px-3 py-3 border-t border-ink-200 sticky bottom-0 bg-white">
        <button
          type="button"
          onClick={onAnalyzeClick}
          disabled={analyzeRunning}
          className="btn-primary w-full"
        >
          {analyzeRunning ? "分析中..." : "运行 LLM 分析"}
        </button>
      </div>
    </aside>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="px-3 py-3 border-b border-ink-200">
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-700">{title}</h3>
        {subtitle && <span className="text-[10px] text-ink-500">{subtitle}</span>}
      </div>
      {children}
    </div>
  );
}

function ytdDays(): number {
  const now = new Date();
  const jan1 = new Date(now.getFullYear(), 0, 1);
  return Math.ceil((now.getTime() - jan1.getTime()) / (24 * 3600 * 1000));
}

function groupBy<T, K>(arr: T[], key: (t: T) => K): Map<K, T[]> {
  const m = new Map<K, T[]>();
  for (const x of arr) {
    const k = key(x);
    if (!m.has(k)) m.set(k, []);
    m.get(k)!.push(x);
  }
  return m;
}
