"use client";

// /panels — index page listing all built panels.
// Companion to /panels/[panelId]; this is the "switcher landing page".

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ErrorBoundary } from "../../components/ErrorBoundary";
import { fetchPanelsList } from "../../lib/api";
import { formatTimestampUtc } from "../../lib/formatting";

export default function PanelsIndexPage() {
  const listQ = useQuery({
    queryKey: ["panels-list"],
    queryFn: () => fetchPanelsList(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  return (
    <ErrorBoundary>
      <main className="min-h-screen bg-ink-50">
        <div className="mx-auto max-w-5xl p-6">
          <header className="mb-6">
            <h1 className="text-2xl font-semibold text-ink-900">PIT Panels</h1>
            <p className="mt-1 text-sm text-ink-500">
              所有已构建的 PIT panel 快照。点击进入研究工作台。
            </p>
          </header>

          {listQ.isLoading && (
            <div className="text-sm text-ink-500">加载中…</div>
          )}

          {listQ.isError && (
            <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
              无法连接后端:{String(listQ.error)}
            </div>
          )}

          {!listQ.isLoading && !listQ.isError && (listQ.data?.count ?? 0) === 0 && (
            <div className="rounded border border-ink-200 bg-white p-6 text-sm text-ink-600">
              <p className="font-medium text-ink-800">尚无 panel</p>
              <p className="mt-2">
                用 CLI 构建一个:
              </p>
              <pre className="mt-2 rounded bg-ink-50 p-3 text-xs font-mono text-ink-700">
                {`cd /vol1/.../PIT-Market-Intelligence-Platform\n. .venv/bin/activate\nexport PYTHONPATH=src PIT_CONFIG_DIR=config PIT_MARKET_DATA=./data PYTHONIOENCODING=utf-8\npit-market pit build --decision-time "2024-06-30T18:05:00Z" --universe "SPY,QQQ,GLD,SLV"`}
              </pre>
            </div>
          )}

          {!listQ.isLoading && !listQ.isError && (listQ.data?.count ?? 0) > 0 && (
            <ul className="space-y-2">
              <li>
                <Link
                  href="/panels/latest"
                  className="block rounded-lg border border-ink-200 bg-white px-4 py-3 hover:border-brand-400 hover:bg-brand-50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-ink-900">latest (auto)</span>
                    <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-medium text-brand-700">
                      LATEST
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-ink-500">
                    跳转到最近一次构建的 panel(后端按 mtime 选)
                  </div>
                </Link>
              </li>

              {listQ.data!.panels.map((p) => (
                <li key={p.panel_id}>
                  <Link
                    href={`/panels/${encodeURIComponent(p.panel_id)}`}
                    className="block rounded-lg border border-ink-200 bg-white px-4 py-3 hover:border-brand-400 hover:bg-brand-50 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm text-ink-900 truncate">
                        {p.panel_id}
                      </span>
                      {p._mtime_utc && (
                        <span className="ml-auto text-xs text-ink-400 font-mono">
                          {formatTimestampUtc(p._mtime_utc)}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-xs text-ink-500 truncate">
                      <span className="font-mono">{p.decision_time_utc ?? "—"}</span>
                      {" · "}
                      <span>{p.decision_clock ?? "1805_ET"}</span>
                      {p.universe && p.universe.length > 0 && (
                        <>
                          {" · universe: "}
                          <span>{p.universe.join(", ")}</span>
                        </>
                      )}
                      {" · "}
                      <span>{p._size_bytes ?? 0} bytes</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          <footer className="mt-6 text-xs text-ink-400">
            <Link href="/dashboard" className="hover:text-brand-600">← 回 Dashboard</Link>
          </footer>
        </div>
      </main>
    </ErrorBoundary>
  );
}