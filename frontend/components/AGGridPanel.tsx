"use client";

// AGGridPanel — server-paginated AG Grid for PIT panel wide-table
// (PRD §AGGridPanel). Quality column shows colored icons. Right-click
// context menu opens EvidenceDrawer / jumps to /lineage / exports row.

import { useCallback, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef, GridReadyEvent, ICellRendererParams, GetContextMenuItemsParams } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { useQuery } from "@tanstack/react-query";
import { useSliceStore } from "../stores/sliceStore";
import { useSelectionStore } from "../stores/selectionStore";
import { fetchTablePage } from "../lib/api";
import { formatNumber, qualityPill, zScoreColor } from "../lib/formatting";
import type { TableRow, QualityStatus } from "../types/api";

const PAGE_SIZE = 50;

export interface AGGridPanelProps {
  panelId: string;
  height?: number;
  onEvidenceOpen?: (evidenceId: string) => void;
}

export function AGGridPanel({ panelId, height = 480, onEvidenceOpen }: AGGridPanelProps) {
  const slice = useSliceStore();
  const [page, setPage] = useState(1);
  const gridRef = useRef<AgGridReact>(null);
  const openLineageForRow = useSelectionStore((s) => s.setOpenRawHash);

  const query = useQuery({
    queryKey: ["table", panelId, page, slice.dateRange.start, slice.dateRange.end, slice.symbols.join(",")],
    queryFn: () =>
      fetchTablePage({
        panel_id: panelId,
        decision_time: slice.decisionTime,
        decision_clock: slice.decisionClock,
        symbols: slice.symbols,
        start: slice.dateRange.start,
        end: slice.dateRange.end,
        page,
        page_size: PAGE_SIZE,
      }),
    enabled: !!panelId && panelId !== "latest",
    staleTime: 30_000,
  });

  const columnDefs = useMemo<ColDef<TableRow>[]>(() => [
    { headerName: "标的", field: "canonical_symbol", pinned: "left", width: 90, cellClass: "font-mono" },
    { headerName: "decision_time", field: "decision_time", width: 170, cellClass: "font-mono text-xs" },
    { headerName: "panel_v", field: "panel_version", width: 110, cellClass: "font-mono text-xs" },
    {
      headerName: "close_raw", field: "close_raw", width: 100,
      valueFormatter: (p) => formatNumber(p.value as number | null),
      cellStyle: (p) => p.value != null ? null : { background: "#fef2f2" },
    },
    {
      headerName: "close_adj", field: "close_adj", width: 100,
      valueFormatter: (p) => formatNumber(p.value as number | null),
    },
    {
      headerName: "z_63d", field: "z_score_63d", width: 80,
      valueFormatter: (p) => formatNumber(p.value as number | null),
      cellStyle: (p) => {
        const c = zScoreColor(p.value as number | null);
        return c ? { background: c } : null;
      },
    },
    {
      headerName: "ret_1d", field: "return_1d", width: 80,
      valueFormatter: (p) => formatNumber(p.value as number | null, 3),
    },
    {
      headerName: "ret_5d", field: "return_5d", width: 80,
      valueFormatter: (p) => formatNumber(p.value as number | null, 3),
    },
    { headerName: "real_rate", field: "real_rate_10y", width: 90, valueFormatter: (p) => formatNumber(p.value as number | null) },
    { headerName: "dxy_z", field: "dxy_z_score", width: 80, valueFormatter: (p) => formatNumber(p.value as number | null), cellStyle: (p) => { const c = zScoreColor(p.value as number | null); return c ? { background: c } : null; } },
    { headerName: "vix", field: "vix_level", width: 70, valueFormatter: (p) => formatNumber(p.value as number | null, 1) },
    { headerName: "hy_spread", field: "hy_spread", width: 90, valueFormatter: (p) => formatNumber(p.value as number | null) },
    { headerName: "MM_net", field: "managed_money_net", width: 100, valueFormatter: (p) => formatNumber(p.value as number | null) },
    { headerName: "cot_pct", field: "cot_net_pct_oi", width: 80, valueFormatter: (p) => formatNumber(p.value as number | null, 3) },
    { headerName: "crowd", field: "crowd_score", width: 80, valueFormatter: (p) => formatNumber(p.value as number | null) },
    { headerName: "short_ratio", field: "short_ratio_finra", width: 100, valueFormatter: (p) => formatNumber(p.value as number | null) },
    { headerName: "short_flow_z", field: "short_flow_z_score", width: 100, valueFormatter: (p) => formatNumber(p.value as number | null), cellStyle: (p) => { const c = zScoreColor(p.value as number | null); return c ? { background: c } : null; } },
    {
      headerName: "quality", field: "quality_status", width: 100, pinned: "right",
      cellRenderer: (p: ICellRendererParams<TableRow, QualityStatus>) => {
        const q = p.value ?? "VALID";
        const pill = qualityPill(q, true);
        return (
          <span className={pill.className} title={pill.label}>
            <span className={`pulse-dot ${pill.dotClass}`} />
            {q}
          </span>
        );
      },
    },
  ], []);

  const onGridReady = useCallback((_e: GridReadyEvent) => { /* placeholder for future */ }, []);

  const getContextMenuItems = useCallback((params: GetContextMenuItemsParams<TableRow>) => {
    if (!params.node?.data) return [];
    const row = params.node.data;
    return [
      {
        name: "查看证据 (Evidence)",
        action: () => {
          const ev = row.evidence_ids?.[0];
          if (ev) onEvidenceOpen?.(ev);
        },
      },
      {
        name: "查看血缘 (Lineage)",
        action: () => {
          openLineageForRow(row.canonical_symbol ?? null);
        },
      },
      {
        name: "导出此行 (CSV)",
        action: () => exportRowCsv(row),
      },
      "separator",
      "copy",
      "copyWithHeaders",
    ] as any;
  }, [onEvidenceOpen, openLineageForRow]);

  const total = query.data?.page_info.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-2 border-b border-ink-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-900">PIT Panel 宽表</h3>
        <div className="text-xs text-ink-500">
          {query.isLoading ? "加载中..." : `${total.toLocaleString()} 行 / 第 ${page} / ${lastPage} 页`}
        </div>
      </div>
      <div className="ag-theme-quartz" style={{ height: `${height}px` }}>
        <AgGridReact<TableRow>
          ref={gridRef}
          columnDefs={columnDefs}
          rowData={query.data?.rows ?? []}
          onGridReady={onGridReady}
          getContextMenuItems={getContextMenuItems}
          suppressCellFocus
          animateRows
          rowSelection="single"
          enableCellChangeFlash={false}
          defaultColDef={{ resizable: true, sortable: true, filter: true }}
        />
      </div>
      <div className="flex items-center justify-between px-4 py-2 border-t border-ink-200 text-xs">
        <button
          type="button"
          className="btn-ghost"
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
        >
          ← 上一页
        </button>
        <div className="text-ink-500 tabular-nums">第 {page} / {lastPage} 页 · 每页 {PAGE_SIZE} 行</div>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
          disabled={page >= lastPage}
        >
          下一页 →
        </button>
      </div>
    </div>
  );
}

function exportRowCsv(row: TableRow) {
  const headers = Object.keys(row).join(",");
  const values = Object.values(row).map((v) =>
    v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v),
  ).join(",");
  const csv = `${headers}\n${values}\n`;
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${row.canonical_symbol}-${row.decision_time}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
