"use client";

// /lineage/[entityId] — data lineage graph (PRD §页面路由 /lineage/[entityId]).

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorBoundary } from "../../../components/ErrorBoundary";
import { PITContextBar } from "../../../components/PITContextBar";
import { FilterRail } from "../../../components/FilterRail";
import { LineageDrawer } from "../../../components/LineageDrawer";
import { EmptyState } from "../../../components/EmptyState";
import { fetchLineage } from "../../../lib/api";
import type { LineageNode, LineageNodeKind } from "../../../types/api";

const LEVELS: LineageNodeKind[] = ["finding", "evidence", "feature", "observation", "raw"];
const LEVEL_LABEL: Record<LineageNodeKind, { zh: string; color: string; bg: string }> = {
  finding:      { zh: "Finding",         color: "#4f46e5", bg: "bg-indigo-50" },
  evidence:     { zh: "Evidence",        color: "#0ea5e9", bg: "bg-sky-50" },
  feature:      { zh: "Feature",         color: "#10b981", bg: "bg-emerald-50" },
  observation:  { zh: "Observation",     color: "#a78bfa", bg: "bg-violet-50" },
  raw:          { zh: "Raw Manifest",    color: "#f59e0b", bg: "bg-amber-50" },
};

export default function LineagePage() {
  const params = useParams<{ entityId: string }>();
  const entityId = params?.entityId ?? "sample";
  const [openInDrawer, setOpenInDrawer] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["lineage", entityId],
    queryFn: () => fetchLineage(entityId),
    enabled: !!entityId,
    staleTime: 60_000,
  });

  const graph = q.data;
  const byLevel: Record<LineageNodeKind, LineageNode[]> = {
    finding: [], evidence: [], feature: [], observation: [], raw: [],
  };
  for (const n of graph?.nodes ?? []) byLevel[n.kind]?.push(n);

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-ink-50">
        <PITContextBar panelId={entityId} qualityStatus="VALID" />
        <div className="flex">
          <FilterRail />
          <main className="flex-1 min-w-0 p-4 space-y-4">
            <div className="card-pad">
              <h1 className="text-base font-semibold text-ink-900 mb-1">5 级血缘</h1>
              <div className="text-xs text-ink-500">
                entity_id: <span className="font-mono text-ink-700">{entityId}</span>
                {" · "}
                {graph ? `${graph.nodes.length} nodes / ${graph.edges.length} edges` : "loading…"}
              </div>
            </div>

            {q.isLoading ? (
              <div className="card h-[400px] skeleton" />
            ) : !graph || graph.nodes.length === 0 ? (
              <div className="card h-[300px] flex items-center justify-center">
                <EmptyState variant="no-data" title="该实体暂无血缘数据" />
              </div>
            ) : (
              <div className="space-y-3">
                {LEVELS.map((lvl) => {
                  const nodes = byLevel[lvl] ?? [];
                  const meta = LEVEL_LABEL[lvl];
                  return (
                    <section key={lvl} className="card-pad">
                      <div className="flex items-center gap-2 mb-3">
                        <span
                          className="w-2.5 h-2.5 rounded-full"
                          style={{ background: meta.color }}
                        />
                        <h2 className="text-sm font-semibold text-ink-900">{meta.zh}</h2>
                        <span className="text-xs text-ink-500">({nodes.length})</span>
                      </div>
                      {nodes.length === 0 ? (
                        <div className="text-xs text-ink-400">无节点</div>
                      ) : (
                        <ul className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                          {nodes.map((n) => (
                            <li
                              key={n.id}
                              className={`${meta.bg} rounded-md p-2.5 border cursor-pointer hover:shadow-sm`}
                              style={{ borderColor: meta.color + "44" }}
                              onClick={() => setOpenInDrawer(n.id)}
                            >
                              <div className="font-mono text-xs text-ink-900 truncate">{n.id}</div>
                              {n.label && <div className="text-xs text-ink-700">{n.label}</div>}
                              {n.sha256 && <div className="text-[10px] text-ink-500 font-mono mt-0.5">sha256: {n.sha256.slice(0, 12)}…</div>}
                            </li>
                          ))}
                        </ul>
                      )}
                    </section>
                  );
                })}
              </div>
            )}
          </main>
        </div>
        {openInDrawer && <LineageDrawer defaultEntityId={openInDrawer} />}
      </div>
    </ErrorBoundary>
  );
}
