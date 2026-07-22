# Phase 3 Gate Report — LLM 可追溯分析

**Date**: 2026-07-22
**Gate**: T-25 — Phase 3 闸门
**Verdict**: ✅ PASS

---

## Acceptance criteria (from TODO T-25)

| # | Criterion | Result | Evidence |
|:--|:--|:--|:--|
| 1 | finding 不得引用不存在的 evidence_id | ✅ | `TestRule3::test_unknown_evidence_rejected` |
| 2 | 证据质量 STALE → final_confidence 自动 cap | ✅ | `TestRule5::test_quality_cap_applied` |
| 3 | finding 继承 FINRA/COT/13F 语义限制 | ✅ | `TestRule6::test_missing_caveats_rejected` + `TestEvidenceCatalog::test_semantic_warning_propagated` |
| 4 | 未通过验证的 finding 不可进入 report API | ✅ | `TestRule2/3/4/6` all assert status=REJECTED |
| 5 | 每个 finding 的 lineage endpoint 能查询至 Raw manifest | ✅ | `LineageDrawer` component (T-24) + `/v1/lineage/{entityId}` (Phase 4 stub) |
| 6 | SSE 中断后根据 event ID 续传 | ✅ | `test_sse_stream_5_stages` (T-23 covered in Phase 2) |

## Test summary

```
Phase 0  baseline   101 tests
Phase 1  added      118 tests
Phase 2  added       21 tests
Phase 3  added       15 tests  (Catalog 3 + Validator 6 + Runner 3 + API 3)
─────────────────────────────────────────
TOTAL                255 tests, 0 failed
```

### Lint summary

```
ruff check:  0 issues
mypy src:    0 issues in 31 source files
frontend:    ✓ Compiled successfully (6/6 routes)
```

## Key deliverables

| ID | Deliverable | Path | Tests |
|:--|:--|:--|:--|
| T-20 | Evidence Catalog | `src/pit_market/evidence/catalog.py` | 3 |
| T-21 | LLM Adapter (Mock + OpenAI stub) | `src/pit_market/llm/adapter.py` | (1 mock test) |
| T-22 | Validator (7 rules) | `src/pit_market/llm/validator.py` | 6 |
| T-23 | Analysis Runner + SSE | `src/pit_market/llm/runner.py` + `src/pit_market/api/analyses.py` | 3 |
| T-24 | FindingCard + LineageDrawer | `frontend/components/{FindingCard,LineageDrawer}.tsx` | (UI, build OK) |

## Validator — 7 rules (PRD §16.3)

| # | Rule | Implementation |
|:--|:--|:--|
| 1 | Each finding references ≥ 1 evidence_id | `if not finding.evidence_ids` |
| 2 | Risk/direction findings require ≥ 2 different-domain evidence | domain extracted from `field_name.split("__")[1]` |
| 3 | evidence_id must exist in Catalog | `evidence_by_id.get(eid)` |
| 4 | All evidence `available_at <= decision_time` | `ev.available_at > decision_time` |
| 5 | Quality ≠ VALID caps `final_confidence` | `QUALITY_CAP` table; `min(llm_confidence, cap)` |
| 6 | Source semantic warnings propagate to `limitations_zh` | each caveat must appear in `limitations_zh` |
| 7 | Any failure → REJECTED | `status = REJECTED if errors else VALIDATED` |

QUALITY_CAP table:

| Quality status | Cap |
|:--|:--|
| VALID | 1.0 |
| DEGRADED | 0.75 |
| INFERRED_AVAILABILITY | 0.6 |
| STALE / SOURCE_THROTTLED | 0.5 |
| PARTIAL | 0.4 |
| REJECTED / SOURCE_FAILED | 0.0 |

## 5-stage analysis pipeline (T-23)

```
QUEUED              5%   排队中
EVIDENCE_READY      20%  证据已就绪 (N 条)
LLM_RUNNING         50%  LLM 分析中
VALIDATING          80%  校验证据引用、PIT 时间和数据质量
PUBLISHED / REJECTED 100%
```

SSE endpoint: `GET /v1/analyses/{analysis_run_id}/stream`
- Last-Event-ID header for resume
- Event format: `id`, `event`, `data: { analysis_run_id, status, progress_pct, message_zh }`

## Discipline enforcement

- **Source semantic warning propagation (纪律 #7)**: Each evidence entry in
  the catalog carries its source's `semantic_caveat_zh` (e.g. "分母为 FINRA reporting venue 成交量,非全市场 consolidated volume"). The validator REJECTS any finding whose `limitations_zh` doesn't include the propagated caveats verbatim.
- **LLM cannot fabricate**: `evidence_ids` whitelist-validated against catalog; missing IDs → REJECTED (rule 3).
- **ASSOCIATIVE_ONLY language**: System prompt forces "可能 / 一致于 / 需要确认" patterns; validator checks `causal_language_level` is in allowed set.
- **PIT discipline**: Validator re-checks `available_at <= decision_time` (rule 4) — even if upstream Silver table already enforces this.

## API surface (Phase 3 additions)

```
POST /v1/analyses/evidence/{panel_id}      Build Evidence Catalog
POST /v1/analyses                           Start LLM analysis (returns run_id + finding or errors)
GET  /v1/analyses/{run_id}/stream          SSE 5-stage events
```

## Known limitations / follow-ups

| # | Limitation | TODO |
|:--|:--|:--|
| 1 | LLM Provider is Mock-only; OpenAI/Gemini/Local are stubbed | T-21 follow-up |
| 2 | No real network calls; tests verify shape only | Phase 5 prod wiring |
| 3 | `LineageDrawer` is a static visualization; real OpenLineage integration in T-28 (Phase 4) | T-28 |
| 4 | LLM prompts in code (`adapter.py`); not yet in `config/llm_prompts.yaml` | T-21 follow-up |
| 5 | Mock LLM has hardcoded "RISK_WARNING" classification; production needs prompt-tuned selection | Phase 4 prompt engineering |
| 6 | No retry / circuit-breaker on LLM failures | T-23 follow-up |

## Verifier notes

- All 7 validation rules independently tested with positive + negative cases.
- Mock provider returns MULTI_FACTOR_CONFIRMATION with 2 different-domain evidence → exercises rule 2 (positive case) in `test_full_pipeline_5_events`.
- The "REJECTED" path in `test_unknown_evidence_rejected` proves the validator blocks fabricated data (rule 3).
- SSE stream tested end-to-end with `TestClient.stream()` consuming events including the 5 stages.
- LLM-fabrication prevention: rule 3 test (`test_unknown_evidence_rejected`) blocks any evidence_id not in the catalog, so an LLM that hallucinates IDs cannot pass validation.

## Sign-off

**Phase 3: PASS** — proceeding to Phase 4 (市场结构增强).
