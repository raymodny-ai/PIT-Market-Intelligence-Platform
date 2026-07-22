"use client";

// /findings/[findingId] — Finding audit page (PRD §页面路由 /findings/[findingId]).
// Full 5-level lineage + evidence cards + LLM chain.

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { ErrorBoundary } from "../../../components/ErrorBoundary";
import { PITContextBar } from "../../../components/PITContextBar";
import { FilterRail } from "../../../components/FilterRail";
import { FindingCard } from "../../../components/FindingCard";
import { EvidenceDrawer } from "../../../components/EvidenceDrawer";
import { LineageDrawer } from "../../../components/LineageDrawer";
import { EmptyState } from "../../../components/EmptyState";
import { useSelectionStore } from "../../../stores/selectionStore";
import { fetchFinding, fetchEvidence, fetchLineage, fetchLLMFacet } from "../../../lib/api";
import { formatTimestamp, formatNumber } from "../../../lib/formatting";

export default function FindingPage() {
  const params = useParams<{ findingId: string }>();
  const findingId = params?.findingId ?? "sample";
  const openRawHash = useSelectionStore((s) => s.openRawHash);

  const findingQ = useQuery({
    queryKey: ["finding", findingId],
    queryFn: () => fetchFinding(findingId),
    enabled: !!findingId,
    staleTime: 60_000,
  });
  const lineageQ = useQuery({
    queryKey: ["lineage", findingId],
    queryFn: () => fetchLineage(findingId),
    enabled: !!findingId,
    staleTime: 60_000,
  });
  const facetQ = useQuery({
    queryKey: ["facet", findingQ.data?.analysis_run_id ?? ""],
    queryFn: () => fetchLLMFacet(findingQ.data!.analysis_run_id!),
    enabled: !!findingQ.data?.analysis_run_id,
    staleTime: 60_000,
  });

  const finding = findingQ.data;

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-ink-50">
        <PITContextBar
          panelId={finding?.finding_id?.slice(0, 16) ?? findingId}
          decisionTime={finding?.created_at ?? new Date().toISOString()}
          qualityStatus={finding?.rejected ? "REJECTED" : "VALID"}
        />
        <div className="flex">
          <FilterRail />
          <main className="flex-1 min-w-0 p-4 space-y-4">
            {finding ? (
              <>
                <FindingCard finding={finding} />
                <section className="card-pad">
                  <h2 className="text-sm font-semibold text-ink-900 mb-2">证据列表</h2>
                  {finding.evidence_ids.length === 0 ? (
                    <EmptyState variant="no-data" title="无关联证据" />
                  ) : (
                    <ul className="space-y-1.5">
                      {finding.evidence_ids.map((id) => (
                        <li key={id} className="text-xs flex items-center justify-between bg-ink-50 rounded px-2 py-1.5">
                          <span className="font-mono text-ink-900">{id}</span>
                          <button
                            type="button"
                            className="btn-ghost text-[11px]"
                            onClick={() => useSelectionStore.getState().openEvidence(id)}
                          >
                            查看
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
                {lineageQ.data && (
                  <section className="card-pad">
                    <h2 className="text-sm font-semibold text-ink-900 mb-2">5 级血缘概览</h2>
                    <div className="grid grid-cols-5 gap-2 text-xs">
                      {(["finding", "evidence", "feature", "observation", "raw"] as const).map((lvl) => {
                        const nodes = (lineageQ.data!.nodes ?? []).filter((n) => n.kind === lvl);
                        return (
                          <div key={lvl} className="bg-ink-50 rounded p-2">
                            <div className="label-muted mb-1">{lvl}</div>
                            <div className="font-mono text-ink-900">{nodes.length} nodes</div>
                          </div>
                        );
                      })}
                    </div>
                    <button
                      type="button"
                      className="btn-ghost mt-3"
                      onClick={() => useSelectionStore.getState().setOpenRawHash(findingId)}
                    >
                      展开完整血缘图 →
                    </button>
                  </section>
                )}
                {facetQ.data && (
                  <section className="card-pad">
                    <h2 className="text-sm font-semibold text-ink-900 mb-2">LLMProvenanceRunFacet (OpenLineage)</h2>
                    <pre className="text-xs bg-ink-900 text-emerald-300 rounded p-3 overflow-x-auto font-mono">
{JSON.stringify(facetQ.data, null, 2)}
                    </pre>
                  </section>
                )}
              </>
            ) : (
              <div className="card h-[300px] flex items-center justify-center">
                <EmptyState
                  variant="no-data"
                  title="finding 未找到"
                  description={`/v1/findings/${findingId} 返回 404 或格式异常`}
                />
              </div>
            )}
          </main>
        </div>
        {finding?.evidence_ids[0] && <EvidenceDrawer panelId={finding.evidence_ids[0]} />}
        {openRawHash && <LineageDrawer defaultEntityId={openRawHash} />}
      </div>
    </ErrorBoundary>
  );
}
