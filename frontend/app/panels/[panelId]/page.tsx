"use client";

// /panels/[panelId] — PIT Panel research station (PRD §页面路由 /panels/[panelId]).
// PITContextBar + FilterRail + AGGridPanel wide table + lineage jump.

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useEffect } from "react";
import { ErrorBoundary } from "../../../components/ErrorBoundary";
import { PITContextBar } from "../../../components/PITContextBar";
import { FilterRail } from "../../../components/FilterRail";
import { AGGridPanel } from "../../../components/AGGridPanel";
import { TimeSeriesChart } from "../../../components/TimeSeriesChart";
import { EmptyState } from "../../../components/EmptyState";
import { EvidenceDrawer } from "../../../components/EvidenceDrawer";
import { LineageDrawer } from "../../../components/LineageDrawer";
import { useSelectionStore } from "../../../stores/selectionStore";
import { useSliceStore } from "../../../stores/sliceStore";
import { fetchPanel, fetchSlice } from "../../../lib/api";

export default function PanelPage() {
  const params = useParams<{ panelId: string }>();
  const panelId = params?.panelId ?? "latest";
  const slice = useSliceStore();
  const openRawHash = useSelectionStore((s) => s.openRawHash);

  useEffect(() => {
    if (panelId && panelId !== "latest") slice.setPanelId(panelId);
  }, [panelId, slice]);

  const panelQ = useQuery({
    queryKey: ["panel", panelId],
    queryFn: () => fetchPanel(panelId),
    enabled: panelId !== "latest",
    staleTime: 30_000,
  });

  const sliceQ = useQuery({
    queryKey: ["slice", panelId, slice.decisionTime, slice.symbols.join(",")],
    queryFn: () => fetchSlice({
      panel_id: panelId,
      decision_time: slice.decisionTime,
      decision_clock: slice.decisionClock,
      symbols: slice.symbols,
      start: slice.dateRange.start,
      end: slice.dateRange.end,
    }),
    enabled: panelId !== "latest",
    staleTime: 30_000,
  });

  if (panelId === "latest") {
    return (
      <div className="p-8">
        <EmptyState
          variant="no-data"
          title="请指定 panel_id"
          description='从 /dashboard 选择具体 panel,或访问 /panels/{panel_id}'
        />
      </div>
    );
  }

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-ink-50">
        <PITContextBar
          panelId={panelQ.data?.panel_id ?? panelId}
          decisionTime={slice.decisionTime}
          panelVersion={panelQ.data?.panel_version}
          featureVersion={panelQ.data?.feature_version}
          qualityStatus={panelQ.data?.quality_status}
        />
        <div className="flex">
          <FilterRail />
          <main className="flex-1 min-w-0 p-4 space-y-4">
            {sliceQ.data?.series?.length ? (
              <TimeSeriesChart series={sliceQ.data.series} title="PIT 时序(本 panel)" height={320} />
            ) : (
              <div className="card h-[340px] flex items-center justify-center">
                <EmptyState
                  variant="no-data"
                  title="该 panel 暂无 PIT 时序"
                  description="可能 panel 尚未构建或数据未 ingest"
                />
              </div>
            )}
            <AGGridPanel panelId={panelId} height={520} />
          </main>
        </div>
        <EvidenceDrawer panelId={panelId} />
        {openRawHash && <LineageDrawer defaultEntityId={openRawHash} />}
      </div>
    </ErrorBoundary>
  );
}
