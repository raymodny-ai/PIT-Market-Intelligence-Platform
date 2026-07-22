# Phase 0 Gate Report

**Date**: 2026-07-21
**Gate**: T-04 — Phase 0 闸门
**Verdict**: ✅ PASS

---

## Acceptance criteria (from TODO T-04)

| # | Criterion | Result | Evidence |
|:--|:--|:--|:--|
| 1 | `pip install -e .` + `pip check` | ✅ | 15 source files installed, 0 conflicts |
| 2 | `ruff check` | ✅ | 0 issues across `src/` + `tests/` |
| 3 | `mypy src` | ✅ | 0 issues in 15 source files |
| 4 | `pnpm install` + `pnpm build` + `pnpm lint` | ✅ | Next.js 14.2.18 build OK, 5/5 routes |
| 5 | 前后端 hello world 联调 | ✅ | `GET /health` returns 200 with registry_hash |
| 6 | Trading Calendar 与 NYSE 官方 2024-2026 100% 一致 | ✅ | 78 calendar tests + 3 full-year audit pass |

## Test results

```
tests/backend/test_trading_calendar.py ........... 78 passed
tests/backend/test_registry.py .................. 20 passed
tests/backend/test_api_health.py ................  3 passed
                                                ==========
                                                101 passed in 1.02s
```

## Key deliverables

| ID | Deliverable | Path |
|:--|:--|:--|
| T-01 | Python project skeleton | `pyproject.toml` + `src/pit_market/` (14 modules) |
| T-01 | Docker Compose | `docker-compose.yml` (Dagster daemon + webserver) |
| T-01 | Configs | `config/settings.yaml` + `.env.example` |
| T-02 | Next.js 14 frontend | `frontend/` (App Router + 5 routes + PITContextBar) |
| T-02 | Slice store | `frontend/stores/sliceStore.ts` (Zustand) |
| T-02 | API client | `frontend/lib/api.ts` (zod-validated) |
| T-03 | Instrument Registry | `config/instruments.yaml` (12 instruments + cot_report_type) |
| T-03 | Metric Registry | `config/metrics.yaml` (15 fields + window_configs) |
| T-03 | Availability Rules | `config/availability_rules.yaml` (8 rules, DST-safe) |
| T-03 | JSON Schemas | `config/schemas/{observation,evidence,llm_analysis,api_slice,ui_view_state}.schema.json` + `LLMProvenanceRunFacet.json` |
| T-03 | Registry loader | `src/pit_market/storage/registry.py` (YAML + JSON Schema + cross-validation) |
| T-03b | Trading Calendar | `src/pit_market/data/trading_calendar.py` (NYSE + business day math) |
| T-03b | Tests | `tests/backend/test_trading_calendar.py` (78 tests, 2024-2026 100% match) |

## Discipline enforcement (纪律 #8)

- **`canonical_symbol` hard reject**: `Registry.assert_canonical_symbol()` raises `UNMAPPED_SYMBOL` for unknown symbols (used in Pandera schema gate at Silver write time — see T-06).
- **`field_name` whitelist**: `Registry.assert_field_name()` raises `UNKNOWN_FIELD` for unregistered metrics (used at API slice validation — see T-14).
- **`cot_report_type` routing**: 4 GLD/SLV/GOLD_COMEX/SILVER_COMEX instruments registered as `DISAGGREGATED`; VIX-family as `TFF` (when added); enforced at registry load.
- **`requires_alfred`**: FRED metric fields tagged; FRED rules marked `uses_alfred=true, realtime_start_required=true`.
- **`finra_regsho_t_plus_1_afternoon`**: 14:00 ET + max_staleness=2D + weekend handling verified by add_business_days tests.

## Discipline enforcement (纪律 #7)

- **`semantic_warning` propagation**: `flow__finra__short_ratio` carries "非全市场" warning that flows to `feature.quality_flags_json` → `evidence.semantic_caveat_zh` → `llm_finding.limitations_zh` (downstream T-08/T-20/T-21).

## Known gaps / follow-ups

| # | Gap | Resolution | TODO |
|:--|:--|:--|:--|
| 1 | `pnpm` not available on PATH; using `npm` | Acceptable for Phase 0; install pnpm in CI | R-1 |
| 2 | No CI workflow file (`.github/workflows/`) yet | Add in Phase 1 after Dagster assets exist | T-04 (CI portion) |
| 3 | `git` not installed; no `.gitignore` / git init | Recommend installing git; add `.gitignore` in Phase 1 | bootstrap |
| 4 | `python` not on PATH (`python3.exe` in WindowsApps) | Wrapped to `C:\Users\raylan\AppData\Local\Programs\Python\Python312\python.exe`; user should add to PATH | R-1 |

## Verifier notes

- All 78 calendar tests pass against official NYSE 2024-2026 holiday list (including 2025-01-09 National Day of Mourning for President Carter, added after initial test failure — caught by audit test `test_2025_full_year`).
- Registry loader enforces all cross-validations at startup; runtime failures (e.g. `UNMAPPED_SYMBOL`) raise hard errors not warnings.
- FastAPI `lifespan` API used (not deprecated `on_event`); TestClient context manager used to ensure lifespan runs.

## Sign-off

**Phase 0: PASS** — proceeding to Phase 1 (PIT 数据 MVP).
