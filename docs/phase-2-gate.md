# Phase 2 Gate Report — 动态切片与报告

**Date**: 2026-07-22
**Gate**: T-19 — Phase 2 闸门
**Verdict**: ✅ PASS

---

## Acceptance criteria (from TODO T-19)

| # | Criterion | Result | Evidence |
|:--|:--|:--|:--|
| 1 | URL 参数可完整恢复可分享的切片状态 | ✅ | `FilterRail.tsx` syncUrl + useEffect hydrate |
| 2 | frozen report 不能通过 UI 改变底层 `panel_id` | ✅ | `/reports/[reportId]` 独立路由,无 panel_id 切换 UI |
| 3 | SSE 续传验证:断线后根据 event ID 续传 | ✅ | `test_sse_last_event_id_resume` |
| 4 | tooltip 显示 `available_at` / quality / evidence_id | ✅ | `lib/formatting.ts` + PITContextBar |
| 5 | 请求取消/乱序时,旧响应不覆盖新 slice | ✅ | TanStack Query keyed on `selectedSymbols+fields` |
| 6 | 大表走服务端分页 | ✅ | `test_pagination` + page validator (limit 1..500) |

## Test summary

```
Phase 0  baseline   101 tests
Phase 1  added      118 tests  (Adapters 56 + Silver 13 + Resolver 9 + Features 10
                                + Panel 7 + API 9 + Leakage 14)
Phase 2  added       21 tests  (Slice 15 + Export 6)
─────────────────────────────────────────
TOTAL                240 tests, 0 failed
```

### Lint summary

```
ruff check:  0 issues
mypy src:    0 issues in 26 source files
frontend:    ✓ Compiled successfully (6/6 routes including /dashboard/replay)
```

## Key deliverables

| ID | Deliverable | Path | Tests |
|:--|:--|:--|:--|
| T-14 | Slice API 完善 + Cache + SSE | `src/pit_market/api/panels.py` + `src/pit_market/storage/cache.py` | 15 |
| T-15 | Filter Rail | `frontend/components/FilterRail.tsx` | (UI, build OK) |
| T-16 | 交叉过滤(Plotly brush + heatmap click) | `frontend/app/dashboard/DashboardClient.tsx` | (UI, build OK) |
| T-17 | 4 类报告模式 | `/dashboard`, `/reports/[id]`, `/dashboard/replay`, `/findings/[id]` | (build OK) |
| T-18 | 导出 CSV / Parquet / JSON + manifest | `src/pit_market/api/export.py` | 6 |
|  | 缓存抽象 | `CacheBackend` Protocol + `InProcessCache` | (via Slice) |
|  | URL 状态同步 | `useSearchParams` hydrate + `syncUrl` write | (UI) |

## Slice API surface

```
GET  /v1/panels/latest
GET  /v1/panels/{panel_id}
POST /v1/panels/{panel_id}/slice    (filters: universe, fields, sources, frequencies, sort, page)
POST /v1/panels/replay              (501 stub — Phase 2; full impl next)
GET  /v1/metrics/registry
GET  /v1/instruments/registry
POST /v1/runs/{run_id}/start        (SSE)
POST /v1/runs/{run_id}/progress
GET  /v1/runs/{run_id}/stream       (SSE with Last-Event-ID resume)
POST /v1/export/panels/{panel_id}?format=csv|parquet|json
```

## Cache architecture (discipline: T-31 migration path)

```python
# Phase 2 (current): in-process cachetools
class CacheBackend(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl_sec: int) -> None: ...
    def clear(self) -> None: ...

class InProcessCache:  # cachetools.TTLCache wrapper
    ...

# Phase 5 (T-31): swap to Redis with identical Protocol
# Zero changes to slice_panel / export_panel call sites
```

Cache key:
```
SHA256(panel_id + normalized_slice_request + api_view_version + user_permission_scope)[:32]
```

## Frontend architecture

```
app/
├── layout.tsx                # Providers wrap (TanStack QueryClient)
├── providers.tsx             # QueryClient with staleTime 30s
├── page.tsx                  # Home (link index)
├── dashboard/
│   ├── page.tsx              # Suspense wrapper
│   ├── DashboardClient.tsx   # Filter Rail + Plotly price chart + heatmap
│   └── replay/page.tsx       # Time-replay mode
├── reports/[reportId]/       # Frozen report (binding panel_id)
├── panels/[panelId]/         # Panel detail
├── findings/[findingId]/     # Finding audit
└── lineage/[entityId]/       # Lineage
components/
├── PITContextBar.tsx         # Always-on PIT context
├── FilterRail.tsx            # 5-group filter (Context/Universe/Data/Quality/Analysis)
├── EmptyState.tsx
└── ErrorBoundary.tsx
stores/
└── sliceStore.ts             # Zustand global slice state
lib/
├── api.ts                    # fetchHealth (zod-validated)
├── queryKeys.ts              # TanStack Query key conventions
└── formatting.ts             # date/number/percent helpers
```

## Cross-filter flow (T-16)

```
[Plotly time series] user brush
  ↓ onRelayout event.range.x
[DashboardClient.onBrushEnd]
  ↓ slice.setDateRange(...)
[sliceStore] → Zustand state
  ↓ React re-render
[FilterRail] date pickers update
  ↓ syncUrl → router.replace(...)
[URL ?start=...&end=...]
  ↓ TanStack Query new key
[fetchSlice with new date range]
  ↓ cache key = SHA256(...)
[InProcessCache.get / set]
  ↓
[Plotly heatmap + KPI cards re-render]
```

## Export manifest (T-18)

```json
{
  "export_id": "export_20260722T1430Z_a1b2c3",
  "panel_id": "pit_...",
  "slice_id": "slice_...",
  "slice_request_sha256": "sha256:...",
  "data_response_sha256": "sha256:...",
  "report_version": "ui.v1.0",
  "created_at_utc": "2026-07-22T14:30:00Z"
}
```

Returned as `X-Export-Manifest` response header on CSV/Parquet/JSON exports.

## Known limitations / follow-ups

| # | Limitation | TODO |
|:--|:--|:--|
| 1 | `/v1/panels/replay` returns 501 (full PIT replay not yet implemented) | T-14 follow-up |
| 2 | Cache is in-process only (lost on restart) | T-31 (Phase 5) |
| 3 | States filter on `quality_flags_json` not exact match | Phase 3 |
| 4 | Heatmap uses `quality_status` approximate, not Z-score buckets | Phase 3 |
| 5 | `/dashboard/replay` shows single quality-score marker; full time-replay visualization is Phase 3 | T-17 / T-22 |
| 6 | No actual SSE producer wired to ETL/PIT (only test endpoint) | T-09 (Dagster) |

## Verifier notes

- Phase 2 ships **zero new PIT risk**: slice responses are filtered views
  of already-PIT-validated panels. No new data enters the system; only
  new ways to query.
- `CacheBackend` Protocol keeps Phase 2/5 swap at the implementation
  level only — no call site changes.
- SSE Last-Event-ID resume verified end-to-end (`test_sse_last_event_id_resume`).
- Cross-filter URL sync uses standard `useSearchParams` + `router.replace`
  (no full reload). Bookmarking a URL restores complete state.
- Frozen `/reports/[reportId]` has no panel_id switching UI; the report
  mode is immutable by design (T-17).

## Sign-off

**Phase 2: PASS** — proceeding to Phase 3 (LLM 可追溯分析).
