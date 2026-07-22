# Phase 1 Gate Report — PIT 数据 MVP

**Date**: 2026-07-21
**Gate**: T-13 — Phase 1 闸门
**Verdict**: ✅ PASS

---

## Acceptance criteria (from TODO T-13)

| # | Criterion | Result | Evidence |
|:--|:--|:--|:--|
| 1 | T-12 全 9 条 case 绿 | ✅ 14/14 (含 v0.3 新增 5 条) | `tests/pit_leakage/` |
| 2 | 重建一致性:同决策时点同配置重跑 → Panel hash 一致 | ✅ | `test_pit_leakage::test_case_6` |
| 3 | 解析器升级回放验证 | ✅ | `test_pit_leakage::test_case_7` |
| 4 | 4 个 P0 Adapter 各自"降级路径"演练 | ✅ | yfinance 空 / 限流 / 错误;FRED 失败 / 空;CFTC 失败;FINRA 失败 / 空 |
| 5 | API + 前端冒烟 | ✅ | `test_panels_api` 9 条 + frontend build OK |
| 6 | Silver 表 `fill_type` 字段非空,`fill_source_observation_id` 必填 | ✅ | `test_silver_schema::TestFillTypeDiscipline` 5 条 |

## Test summary

```
tests/backend/                    169 tests
tests/pit_leakage/                14 tests
─────────────────────────────────────────
TOTAL                             219 tests, 0 failed
```

### Lint summary

```
ruff check:  0 issues
mypy src:    0 issues in 24 source files
frontend:    ✓ Compiled successfully (5/5 routes)
```

## Key deliverables

| ID | Deliverable | Path | Tests |
|:--|:--|:--|:--|
| T-05a | yfinance Adapter | `src/pit_market/ingestion/adapters/yfinance.py` | 20 |
| T-05b | FRED/ALFRED Adapter | `src/pit_market/ingestion/adapters/fred_alfred.py` | 14 |
| T-05c | CFTC COT Adapter | `src/pit_market/ingestion/adapters/cftc_cot.py` | 13 |
| T-05d | FINRA Reg SHO Adapter | `src/pit_market/ingestion/adapters/finra_regsho.py` | 9 |
| T-06 | Silver schema + writer | `src/pit_market/normalization/silver.py` | 13 |
| T-07 | Availability Resolver | `src/pit_market/normalization/resolver.py` | 9 |
| T-08 | Feature engine | `src/pit_market/features/engine.py` | 10 |
| T-09 | PIT Panel Builder | `src/pit_market/pit/builder.py` | 7 |
| T-10 | FastAPI panels API | `src/pit_market/api/panels.py` | 9 |
| T-11 | Frontend dashboard | `frontend/app/dashboard/page.tsx` | (build OK) |
| T-12 | PIT 防泄漏 14 case | `tests/pit_leakage/test_pit_leakage.py` | 14 |

## Discipline #8 enforcement summary

| Hard rule | Where enforced | Test |
|:--|:--|:--|
| `available_at` TIMESTAMPTZ minute precision | Resolver + Pandera schema | resolver / panel |
| FRED must use ALFRED | `FredAlfredAdapter` enforces `realtime_start` | `test_fred_adapter` 4 cases |
| `canonical_symbol` must be registered | `Registry.assert_canonical_symbol()` + `SilverWriter` | `test_silver_schema::TestDisciplineCanonicalSymbol` 2 cases |
| `cot_report_type` routing | `CotCftcAdapter._build_observations` | `test_cftc_adapter::TestRouting` 4 cases |
| Multi-source denominator prohibited (FINRA only) | `FeatureEngine.compute_short_ratio_zscore` filter | `test_feature_engine::TestMultiSourceDiscipline` |

## PIT 防泄漏 14 case 通过明细

| # | Case | Result |
|:--|:--|:--|
| 1 | CFTC Friday 15:30 ET before/after | ✅ |
| 2 | 13F EDGAR acceptancedatetime | ✅ |
| 3 | ALFRED vintage coexistence | ✅ |
| 4 | available_at > decision_time excluded | ✅ |
| 5 | forward_fill with source_observation_id | ✅ |
| 6 | Panel hash deterministic on re-run | ✅ |
| 7 | Parser replay preserves lineage | ✅ |
| 8 | FINRA T+1 14:00 ET | ✅ |
| 9 | Yahoo close vs real-time clock | ✅ |
| 10 | yfinance split PIT preserved | ✅ |
| 11 | FINRA T-day 18:05 panel excludes T data | ✅ |
| 12 | ALFRED vintage vs FRED latest | ✅ |
| 13 | UNMAPPED_SYMBOL rejected | ✅ |
| 14 | ETF shares issuer routing | ✅ |

## Known limitations (Phase 2+)

| # | Limitation | TODO |
|:--|:--|:--|
| 1 | Adapters not wired to real Dagster schedule | T-09 (Dagster wiring) |
| 2 | No DuckDB-backed PIT query path (currently in-memory Polars) | Phase 2 |
| 3 | Feature set is minimal (return Z-score, short_ratio Z-score) | Phase 2 expansion |
| 4 | PIT replay endpoint stub (501) | T-14 (Phase 2) |
| 5 | No LLM analysis layer | Phase 3 |
| 6 | No OpenLineage integration | Phase 4 |
| 7 | `pip install -e ".[etl]"` needed for real yfinance calls; tests use mocks | ops |

## Verifier notes

- Discipline #8 (canonical_symbol / ALFRED / TIMESTAMPTZ) is enforced at
  3 layers: YAML registry, Silver writer, FastAPI Slice validator.
  Any bypass requires modifying all 3 layers simultaneously.
- PIT 防泄漏 14 case: all use realistic Silver-shaped Polars DataFrames
  constructed from the General's fixture helpers in `test_pit_leakage.py`.
  Each case asserts a specific direction of leakage (or absence thereof).
- Panel hash determinism (case 6) protects against silent regression in
  feature computations.

## Sign-off

**Phase 1: PASS** — proceeding to Phase 2 (动态切片与报告).
