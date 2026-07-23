"use client";

// /panels/new — build a new PIT panel manifest.
//
// Form fields:
//   - decision_time (ISO-8601; defaults to next ET 18:05 from "now")
//   - decision_clock (1605_ET | 1805_ET; default 1805_ET)
//   - universe (chip picker over the instruments registry, default SPY,QQQ,GLD,SLV)
//
// Submit hits POST /v1/panels/build. On success: invalidate the panels-list
// query (so PanelSwitcher re-fetches) and navigate to /panels/{new_id}.
//
// PIT-aware defaults:
//   - The default decision_time is the *next* 18:05 ET (or 16:05 if clock
//     is switched), computed on the client after mount to avoid SSR/CSR
//     hydration drift.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorBoundary } from "../../../components/ErrorBoundary";
import { fetchInstruments, buildPanel, fetchPanelsList } from "../../../lib/api";
import { useMounted } from "../../../lib/useMounted";
import type { BuildPanelResponse } from "../../../lib/api";

interface Instrument {
  canonical_symbol: string;
  asset_class: string;
  display_name_zh?: string;
  display_name_en?: string;
}

function toIsoDateInput(d: Date): string {
  // Returns YYYY-MM-DDTHH:MM for a datetime-local input.
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
}

function isoDateInputToUtcIso(local: string): string {
  // datetime-local has no TZ; treat it as local time and convert to UTC ISO.
  const d = new Date(local);
  return d.toISOString();
}

function nextDecisionTime(clock: "1605_ET" | "1805_ET"): Date {
  // Pick the next occurrence of the decision clock in ET. We use a simple
  // 4-hour offset estimate (ET = UTC-4 in DST, UTC-5 in standard) — good
  // enough for a default value; users will fine-tune.
  // ET in minutes from UTC: -240 (DST) or -300 (standard).
  const now = new Date();
  const month = now.getUTCMonth() + 1;
  const isDst = month >= 3 && month <= 10; // rough; actual DST is more complex
  const etOffsetMin = isDst ? -240 : -300;
  const targetHour = clock === "1605_ET" ? 16 : 18;
  const targetMin = 5;
  // Build the next occurrence in UTC.
  const utcNowMs = now.getTime();
  const candidateUtcMs = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate(),
    targetHour - Math.floor(etOffsetMin / 60),
    targetMin - (etOffsetMin % 60),
    0,
    0,
  );
  let target = new Date(candidateUtcMs);
  if (target.getTime() <= utcNowMs) {
    // Already passed today; roll to tomorrow.
    target = new Date(candidateUtcMs + 24 * 3600 * 1000);
  }
  return target;
}

export default function NewPanelPage() {
  const router = useRouter();
  const mounted = useMounted();
  const qc = useQueryClient();

  const instrumentsQ = useQuery({
    queryKey: ["instruments"],
    queryFn: () => fetchInstruments(),
    staleTime: 5 * 60_000,
  });

  const [clock, setClock] = useState<"1605_ET" | "1805_ET">("1805_ET");
  // decisionTime is a datetime-local string (no TZ); converted to ISO on submit.
  const [decisionLocal, setDecisionLocal] = useState<string>("");
  const [universe, setUniverse] = useState<string[]>(["SPY", "QQQ", "GLD", "SLV"]);
  const [error, setError] = useState<string | null>(null);

  // After mount, prefill decision_time with the *next* decision clock in ET.
  useEffect(() => {
    if (!mounted) return;
    if (decisionLocal === "") {
      setDecisionLocal(toIsoDateInput(nextDecisionTime(clock)));
    }
  }, [mounted, clock, decisionLocal]);

  // If clock changes after prefill, recompute to keep the default coherent.
  function handleClockChange(next: "1605_ET" | "1805_ET") {
    setClock(next);
    setDecisionLocal(toIsoDateInput(nextDecisionTime(next)));
  }

  const submit = useMutation({
    mutationFn: async (): Promise<BuildPanelResponse> => {
      if (!decisionLocal) throw new Error("decision_time 为必填");
      if (universe.length === 0) throw new Error("universe 至少选一个标的");
      const r = await buildPanel({
        decision_time: isoDateInputToUtcIso(decisionLocal),
        universe,
        decision_clock: clock,
      });
      if (!r.ok) {
        // Tri-state result: surface the server's actual error message
        // (Pydantic field name, FastAPI detail string, network error, etc.)
        // instead of a generic "no response" toast.
        const prefix = r.status === 0 ? "" : `[${r.status}] `;
        throw new Error(`${prefix}${r.detail}`);
      }
      return r.data;
    },
    onSuccess: async (data) => {
      // Invalidate so PanelSwitcher re-fetches.
      await qc.invalidateQueries({ queryKey: ["panels-list"] });
      router.push(`/panels/${encodeURIComponent(data.panel_id)}`);
    },
    onError: (e: any) => {
      setError(e?.message ?? String(e));
    },
  });

  const instruments = instrumentsQ.data ?? [];
  const symbolByClass = useMemo(() => {
    const byClass = new Map<string, Instrument[]>();
    for (const i of instruments) {
      const arr = byClass.get(i.asset_class) ?? [];
      arr.push(i);
      byClass.set(i.asset_class, arr);
    }
    return byClass;
  }, [instruments]);

  function toggleSymbol(sym: string) {
    setUniverse((u) =>
      u.includes(sym) ? u.filter((s) => s !== sym) : [...u, sym].sort(),
    );
  }

  const todayCount = useMemo(() => {
    // Sanity preview: how many panels already exist for this decision_time?
    if (!decisionLocal) return 0;
    const targetIso = isoDateInputToUtcIso(decisionLocal);
    const list = qc.getQueryData<{ panels: any[]; count: number }>(["panels-list"]);
    if (!list) return 0;
    return list.panels.filter((p) => p.decision_time_utc === targetIso).length;
  }, [decisionLocal, qc]);

  return (
    <ErrorBoundary>
      <main className="min-h-screen bg-ink-50">
        <div className="mx-auto max-w-3xl p-6">
          <header className="mb-6">
            <Link href="/panels" className="text-xs text-brand-600 hover:underline">
              ← 回 Panels
            </Link>
            <h1 className="mt-2 text-2xl font-semibold text-ink-900">新建 PIT Panel</h1>
            <p className="mt-1 text-sm text-ink-500">
              选定一个 <span className="font-mono">decision_time</span>(决策时点)+{" "}
              <span className="font-mono">universe</span>(标的集合),系统会构建 PIT 面板 manifest 并写入
              <code className="ml-1 rounded bg-ink-100 px-1">data/gold/pit_panels/</code>。
            </p>
          </header>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              setError(null);
              submit.mutate();
            }}
            className="space-y-6 rounded-lg border border-ink-200 bg-white p-5"
          >
            {/* decision_time + clock */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="md:col-span-2">
                <label className="mb-1 block text-sm font-medium text-ink-800">
                  decision_time
                </label>
                <input
                  type="datetime-local"
                  value={decisionLocal}
                  onChange={(e) => setDecisionLocal(e.target.value)}
                  required
                  className="w-full rounded border border-ink-200 px-2 py-1.5 text-sm font-mono focus:outline-none focus:border-brand-400"
                />
                <p className="mt-1 text-[11px] text-ink-500">
                  浏览器本地时区;提交时换算成 UTC ISO 8601。
                </p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-ink-800">
                  decision_clock
                </label>
                <div className="flex gap-1">
                  {(["1605_ET", "1805_ET"] as const).map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => handleClockChange(c)}
                      className={`flex-1 rounded border px-2 py-1.5 text-sm font-mono transition-colors ${
                        clock === c
                          ? "border-brand-500 bg-brand-50 text-brand-700"
                          : "border-ink-200 bg-white text-ink-700 hover:border-brand-300"
                      }`}
                    >
                      {c}
                    </button>
                  ))}
                </div>
                <p className="mt-1 text-[11px] text-ink-500">
                  ET 收盘(18:05)或盘后(16:05)决策时点。
                </p>
              </div>
            </div>

            {/* duplicate warning */}
            {todayCount > 0 && (
              <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                ⚠ 当前 decision_time 下已存在 <strong>{todayCount}</strong> 个 panel,新 panel 的 panel_id 会与
                现有不同(因为 universe 决定),但 manifest 文件名按 panel_id 命名不会冲突。
              </div>
            )}

            {/* universe picker */}
            <div>
              <label className="mb-1 block text-sm font-medium text-ink-800">
                universe <span className="text-ink-400">({universe.length} 已选)</span>
              </label>
              {instrumentsQ.isLoading && (
                <div className="text-sm text-ink-500">加载标的列表…</div>
              )}
              {instrumentsQ.isError && (
                <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
                  无法连接后端 — {String(instrumentsQ.error)}
                </div>
              )}
              {symbolByClass.size > 0 && (
                <div className="space-y-3">
                  {Array.from(symbolByClass.entries()).map(([assetClass, items]) => (
                    <div key={assetClass}>
                      <div className="mb-1 text-[11px] uppercase tracking-wide text-ink-400">
                        {assetClass}
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {items.map((i) => {
                          const selected = universe.includes(i.canonical_symbol);
                          return (
                            <button
                              key={i.canonical_symbol}
                              type="button"
                              onClick={() => toggleSymbol(i.canonical_symbol)}
                              className={`rounded-full border px-3 py-1 text-xs font-mono transition-colors ${
                                selected
                                  ? "border-brand-500 bg-brand-100 text-brand-800"
                                  : "border-ink-200 bg-white text-ink-700 hover:border-brand-300"
                              }`}
                              title={i.display_name_zh ?? i.display_name_en ?? i.canonical_symbol}
                            >
                              {i.canonical_symbol}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* preview panel_id */}
            {decisionLocal && universe.length > 0 && (
              <div className="rounded border border-ink-200 bg-ink-50 px-3 py-2 text-xs">
                <div className="text-ink-500">预览 panel_id</div>
                <div className="mt-1 font-mono text-ink-900">
                  cli-
                  {(() => {
                    try {
                      const d = new Date(decisionLocal);
                      const yyyy = d.getUTCFullYear();
                      const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
                      const dd = String(d.getUTCDate()).padStart(2, "0");
                      const hh = String(d.getUTCHours()).padStart(2, "0");
                      const mi = String(d.getUTCMinutes()).padStart(2, "0");
                      const ss = String(d.getUTCSeconds()).padStart(2, "0");
                      return `${yyyy}${mm}${dd}T${hh}${mi}${ss}Z-${universe.join("-")}`;
                    } catch {
                      return "?";
                    }
                  })()}
                </div>
              </div>
            )}

            {error && (
              <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="flex items-center justify-end gap-2">
              <Link
                href="/panels"
                className="rounded border border-ink-200 bg-white px-3 py-1.5 text-sm text-ink-700 hover:bg-ink-50"
              >
                取消
              </Link>
              <button
                type="submit"
                disabled={submit.isPending || universe.length === 0 || !decisionLocal}
                className="rounded bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submit.isPending ? "构建中…" : "构建 panel"}
              </button>
            </div>
          </form>
        </div>
      </main>
    </ErrorBoundary>
  );
}