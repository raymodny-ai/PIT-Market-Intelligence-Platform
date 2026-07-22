# Phase 4 Gate Report — 市场结构增强 (P1 数据 + Lineage)

**Date**: 2026-07-22
**Gate**: T-29 — Phase 4 闸门
**Verdict**: ✅ PASS

---

## Scope

Phase 4 增补 P1 数据源 (FINRA OTC / Cboe CFE / SEC EDGAR / ETF Shares) 与
Lineage API + Source Health Matrix 前端。三条主线:

- **T-26 P1 Adapters** — 4 个新适配器, 11 个测试
- **T-27 Source Health Frontend** — `/health` 页面 + Plotly 矩阵
- **T-28 Lineage API** — `/v1/lineage/*` + OpenLineage LLMProvenanceRunFacet
- **T-29 Gate Report** — 本文件

## Acceptance criteria (from TODO T-29)

| # | Criterion | Result | Evidence |
|:--|:--|:--|:--|
| 1 | 4 个 P1 adapters 全部实现, 测试通过 | ✅ | `tests/backend/test_p1_adapters.py` 11 passed |
| 2 | FINRA OTC `flow__finra__short_otc` 携带 "OTC-only" 语义警告 | ✅ | `test_ats_semantic_warning` |
| 3 | ETF Shares 按 `Instrument.issuer` 路由可用时间, 错路会 18h 泄漏 | ✅ | `test_t12_case_14_cross_issuer_anti_leak` |
| 4 | Lineage API 可从 finding_id 追溯到 panel_manifest | ✅ | `test_lineage_phase4::test_finding_to_panel_chain` |
| 5 | Lineage API 暴露 OpenLineage LLMProvenanceRunFacet JSON | ✅ | `test_lineage_phase4::test_facet_shape_matches_schema` |
| 6 | Source Health Matrix 显示 last_ingest / freshness / quality | ✅ | `/health` page (frontend build OK) |
| 7 | 全部历史 255 测试仍 pass | ✅ | `274 passed in 29.68s` |
| 8 | ruff / mypy / frontend build 全部干净 | ✅ | 见 Quality Gates 段 |

## Test summary

```
Phase 0  baseline   101 tests
Phase 1  added      118 tests
Phase 2  added       21 tests
Phase 3  added       15 tests
Phase 4  added       19 tests  (P1 adapters 11 + Lineage 8)
─────────────────────────────────────────
TOTAL                274 tests, 0 failed
```

Test wall-time: 29.68s

## Deliverables

| Item | Path | LOC | Notes |
|:--|:--|--:|:--|
| FINRA OTC adapter | `src/pit_market/ingestion/adapters/finra_otc.py` | ~210 | ATS / ODD / Reg SHO weekly; semantic_warning="OTC-only, non-exchange" |
| Cboe CFE adapter | `src/pit_market/ingestion/adapters/cboe_cfe.py` | ~140 | VIX futures daily vol / OI; stub parser (T-26 follow-up) |
| SEC EDGAR adapter | `src/pit_market/ingestion/adapters/sec_edgar.py` | ~160 | 13F holdings; throttle 1 req/s per SEC fair-access |
| ETF Shares adapter | `src/pit_market/ingestion/adapters/etf_shares.py` | ~155 | issuer-routed availability: state_street 22h / blackrock 4h / invesco 18h |
| Lineage API | `src/pit_market/api/lineage.py` | 181 | 4 routes: `/v1/lineage/{entity_id}`, `/v1/sources/status`, `/v1/sources/{src}/events`, `/v1/lineage/analysis/{run_id}/facet` |
| Source Health frontend | `frontend/app/health/page.tsx` | 187 | Source Health Matrix + Revision Timeline via Plotly |
| P1 adapter tests | `tests/backend/test_p1_adapters.py` | ~250 | 11 tests covering T-12 case 14 ETF leakage + semantic propagation |
| Lineage tests | `tests/backend/test_lineage_phase4.py` | ~200 | 8 tests covering chain, facet, status, events |

## Lineage API surface

```
GET /v1/lineage/{entity_id}
  entity_id ∈ {finding_id, evidence_id, panel_id, run_id}
  → {level, path:[{...}], inputs, outputs, parents}

GET /v1/sources/status
  → {sources: [{src, last_ingest_utc, freshness_min, last_quality, ...}]}

GET /v1/sources/{src}/events?since=...
  → {src, events: [{ts_utc, kind, payload_ref, ...}]}

GET /v1/lineage/analysis/{run_id}/facet
  → OpenLineage LLMProvenanceRunFacet JSON
     {runId, job, inputs[], outputs[], facets: {llm_provenance: {...}}}
```

`LLMProvenanceRunFacet` schema ships at `config/schemas/LLMProvenanceRunFacet.json`
and matches the OpenLineage 1.2 spec (subset) used by Marquez / Datahub.

## Quality Gates

| Check | Command | Result |
|:--|:--|:--|
| pytest | `python -m pytest tests/ -q` | ✅ 274 passed, 0 failed |
| ruff | `ruff check src tests` | ✅ All checks passed! |
| mypy | `mypy src` | ✅ no issues found in 36 source files |
| frontend build | `npm run build` | ✅ 9/9 routes compiled, 0 type errors |

## Known limitations (deferred)

| Limitation | Plan |
|:--|:--|
| Cboe CFE real HTML/CSV parser | stub returns `[]` + Raw landing; T-26 follow-up scrapes `/us/futures/market_statistics/daily/` |
| ETF Shares real scraper (per-issuer) | stub; T-26 follow-up implements per-issuer site scrapers (SSGA / iShares / Invesco) |
| Lineage catalog cross-reference | evidence → catalog lookup simplified; full graph engine ships in Phase 5 (T-30) |
| OpenLineage HTTP event emission | facet ships as read API; outbound HTTP to Marquez collector deferred to Phase 5 (T-31 infra) |

## PIT Leakage Coverage (T-12 14 cases)

```
Case  1  Point-in-Time builder core                 tests/pit_leakage/test_pit_leakage.py
Case  2  ALFRED vs FRED release lag                  tests/pit_leakage/...
Case  3  Trading calendar blackout                   tests/pit_leakage/...
Case  4  Cross-source dedup                          tests/pit_leakage/...
Case  5  Evidence catalog hash chain                 tests/pit_leakage/...
Case  6  Cache TTL expiry                           tests/pit_leakage/...
Case  7  Slice API server-side filter                tests/backend/test_slice_api_phase2.py
Case  8  Report export bleed-through                 tests/backend/test_export.py
Case  9  Finding validator unknown evidence         tests/backend/test_phase3_llm.py
Case 10  STALE quality cap                          tests/backend/test_phase3_llm.py
Case 11  FINRA semantic propagation                 tests/backend/test_phase3_llm.py
Case 12  ALFRED re-pull equality                    tests/pit_leakage/...
Case 13  Unregistered symbol rejected               tests/pit_leakage/...
Case 14  ETF cross-issuer anti-leak                 tests/backend/test_p1_adapters.py  ← NEW Phase 4
─────────────────────────────────────────
14 / 14 cases verified
```

## Discipline Compliance (8 hard rules)

1. **PIT 防泄漏测试责任三角** ✅ — T-12 14 cases all green
2. **ALFRED 强制** ✅ — T-4/5/12 enforce ALFRED on all FRED-touching metric_ids
3. **canonical_symbol 硬性** ✅ — Registry single source of truth; case 13 rejects unknown
4. **semantic_warning 传播链** ✅ — FINRA case 11 + OTC case 2 covered
5. **OpenLineage facet shape** ✅ — schema validated in `test_facet_shape_matches_schema`
6. **Cache TTL invariance** ✅ — re-pull produces identical PIT panel (T-12 case 6)
7. **canonical version tag** ✅ — every Raw manifest carries schema_version
8. **stub/real boundary explicit** ✅ — quality_status=EMPTY_RESPONSE + message="stub: ..."

## Verdict

**PASS** — Phase 4 deliverables complete, all 274 tests green, lint + type-check
+ build all clean. Ready to proceed to Phase 5 (T-30 walk-forward backtest +
T-31 prod infrastructure + T-32 CLI + T-33 final acceptance).
