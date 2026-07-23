"""Phase 3 LLM tests (T-20 / T-21 / T-22 / T-23 acceptance)."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from pit_market.api.main import app
from pit_market.evidence.catalog import EvidenceCatalog, EvidenceCatalogBuilder
from pit_market.llm.adapter import LLMAdapter, LLMProvider, MockProvider
from pit_market.llm.runner import AnalysisRunner
from pit_market.llm.validator import (
    CausalLanguageLevel,
    Finding,
    FindingClassification,
    FindingValidator,
    ValidationStatus,
)
from pit_market.pit.builder import PitPanelBuilder
from pit_market.storage.registry import Registry

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(CONFIG_DIR)


def _silver_rows_for_cot_fred() -> pl.DataFrame:
    """Mixed-source panel for evidence catalog tests."""
    return pl.DataFrame([
        {
            "observation_id": "obs_cot_1",
            "canonical_symbol": "GLD",
            "field_name": "position__cftc__managed_money_net",
            "value": 50000.0,
            "price_type": None,
            "observation_time": datetime(2024, 1, 9, 21, 0, tzinfo=UTC),
            "available_at": datetime(2024, 1, 12, 20, 30, tzinfo=UTC),
            "valid_from": datetime(2024, 1, 9, 21, 0, tzinfo=UTC),
            "valid_to": None,
            "source_name": "cftc",
            "dataset_name": "disagg_cot",
            "frequency": "weekly",
            "quality_status": "VALID",
            "quality_flags_json": "{}",
            "fill_type": "OBSERVED",
            "raw_record_hash": "cot_hash_001",
            "feature_observation_id": "feat_cot_1",
        },
        {
            "observation_id": "obs_fred_1",
            "canonical_symbol": "QQQ",
            "field_name": "macro__fred__dgs10",
            "value": 4.20,
            "price_type": None,
            "observation_time": datetime(2024, 1, 2, 0, 0, tzinfo=UTC),
            "available_at": datetime(2024, 1, 3, 18, 0, tzinfo=UTC),
            "valid_from": datetime(2024, 1, 2, 0, 0, tzinfo=UTC),
            "valid_to": None,
            "source_name": "fred",
            "dataset_name": "DGS10",
            "frequency": "daily",
            "quality_status": "VALID",
            "quality_flags_json": "{}",
            "fill_type": "OBSERVED",
            "raw_record_hash": "fred_hash_001",
            "feature_observation_id": "feat_fred_1",
        },
    ])


# =============================================================================
# T-20: Evidence Catalog
# =============================================================================


class TestEvidenceCatalog:
    def test_build_basic(self, registry: Registry) -> None:
        panel = _silver_rows_for_cot_fred()
        decision = datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
        catalog = EvidenceCatalogBuilder(registry).build(
            "panel_x", panel, decision
        )
        assert catalog.catalog_id.startswith("catalog_")
        assert len(catalog.evidence_catalog) == 2
        e = catalog.evidence_catalog[0]
        assert e.evidence_id.startswith("ev_")
        assert e.semantic_caveat_zh  # propagated from registry

    def test_skips_null_values(self, registry: Registry) -> None:
        df = pl.DataFrame([
            {
                "observation_id": "obs_1", "canonical_symbol": "QQQ",
                "field_name": "price__yf__close", "value": 100.0,
                "price_type": "RAW_CLOSE",
                "observation_time": datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
                "available_at": datetime(2024, 1, 9, 18, 0, tzinfo=UTC),
                "valid_from": datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
                "valid_to": None, "source_name": "yfinance",
                "dataset_name": "daily_ohlcv", "frequency": "daily",
                "quality_status": "VALID", "quality_flags_json": "{}",
                "fill_type": "OBSERVED", "raw_record_hash": "h1",
            },
            {
                "observation_id": "obs_2", "canonical_symbol": "QQQ",
                "field_name": "price__yf__close", "value": None,  # null
                "price_type": "RAW_CLOSE",
                "observation_time": datetime(2024, 1, 9, 16, 0, tzinfo=UTC),
                "available_at": datetime(2024, 1, 10, 18, 0, tzinfo=UTC),
                "valid_from": datetime(2024, 1, 9, 16, 0, tzinfo=UTC),
                "valid_to": None, "source_name": "yfinance",
                "dataset_name": "daily_ohlcv", "frequency": "daily",
                "quality_status": "VALID", "quality_flags_json": "{}",
                "fill_type": "OBSERVED", "raw_record_hash": "h2",
            },
        ])
        catalog = EvidenceCatalogBuilder(registry).build(
            "panel_y", df, datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
        )
        assert len(catalog.evidence_catalog) == 1

    def test_semantic_warning_propagated(self, registry: Registry) -> None:
        """Discipline #7: FINRA '非全市场' warning must appear in evidence."""
        df = pl.DataFrame([
            {
                "observation_id": "obs_fr",
                "canonical_symbol": "QQQ",
                "field_name": "flow__finra__short_ratio",
                "value": 0.42,
                "price_type": None,
                "observation_time": datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
                "available_at": datetime(2024, 1, 9, 14, 0, tzinfo=UTC),
                "valid_from": datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
                "valid_to": None, "source_name": "finra",
                "dataset_name": "regsho_daily", "frequency": "daily",
                "quality_status": "VALID", "quality_flags_json": "{}",
                "fill_type": "OBSERVED", "raw_record_hash": "h_fr",
            },
        ])
        catalog = EvidenceCatalogBuilder(registry).build(
            "panel_z", df, datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
        )
        e = catalog.evidence_catalog[0]
        assert "非全市场" in e.semantic_caveat_zh


# =============================================================================
# T-22: Validator (7 rules)
# =============================================================================


def _build_finding(evidence_ids: list[str], classification: str = "RISK_WARNING", **kwargs) -> Finding:
    base = {
        "finding_id": "finding_1",
        "title_zh": "示例",
        "claim_zh": "可能存在风险",
        "classification": classification,
        "support_type": "MULTI_FACTOR_CONFIRMATION",
        "causal_language_level": CausalLanguageLevel.ASSOCIATIVE_ONLY.value,
        "llm_confidence": 0.8,
        "final_confidence": 0.8,
        "evidence_ids": evidence_ids,
        "limitations_zh": [],
    }
    base.update(kwargs)
    return Finding(**base)


@pytest.fixture
def small_catalog(registry: Registry) -> EvidenceCatalog:
    panel = _silver_rows_for_cot_fred()
    return EvidenceCatalogBuilder(registry).build(
        "panel_test", panel, datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
    )


class TestRule1:
    def test_no_evidence_rejected(self, small_catalog: EvidenceCatalog) -> None:
        finding = _build_finding(evidence_ids=[])
        result = FindingValidator().validate(finding, small_catalog, datetime(2024, 1, 15, tzinfo=UTC))
        assert result.status == ValidationStatus.REJECTED
        assert any("rule 1" in e for e in result.errors)

    def test_no_evidence_escape_hatch_for_data_quality_issue(self, small_catalog: EvidenceCatalog) -> None:
        """DATA_QUALITY_ISSUE + NO_EVIDENCE findings are allowed to have an empty
        evidence_ids list. This is the legitimate LLM response for an empty
        catalog (manifest-only CLI panels) — the LLM is correctly reporting
        'I have nothing to say' rather than fabricating data.
        """
        finding = _build_finding(
            evidence_ids=[],
            classification="DATA_QUALITY_ISSUE",
            support_type="NO_EVIDENCE",
        )
        result = FindingValidator().validate(finding, small_catalog, datetime(2024, 1, 15, tzinfo=UTC))
        assert result.status != ValidationStatus.REJECTED
        assert not any("rule 1" in e for e in result.errors)

    def test_no_evidence_with_risk_warning_still_rejected(self, small_catalog: EvidenceCatalog) -> None:
        """The escape hatch only applies to DATA_QUALITY_ISSUE findings — a
        RISK_WARNING with zero evidence_ids must still fail rule 1.
        """
        finding = _build_finding(
            evidence_ids=[],
            classification="RISK_WARNING",
            support_type="MULTI_FACTOR_CONFIRMATION",
        )
        result = FindingValidator().validate(finding, small_catalog, datetime(2024, 1, 15, tzinfo=UTC))
        assert result.status == ValidationStatus.REJECTED
        assert any("rule 1" in e for e in result.errors)


class TestRule2:
    def test_risk_finding_needs_two_domains(self, small_catalog: EvidenceCatalog) -> None:
        # Get only the COT evidence_id
        cot_evidence = [e.evidence_id for e in small_catalog.evidence_catalog if "cftc" in e.field_name]
        finding = _build_finding(
            evidence_ids=cot_evidence,
            classification=FindingClassification.RISK_WARNING.value,
        )
        result = FindingValidator().validate(
            finding, small_catalog, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert result.status == ValidationStatus.REJECTED
        assert any("rule 2" in e for e in result.errors)

    def test_risk_finding_two_domains_validated(self, small_catalog: EvidenceCatalog) -> None:
        all_ids = [e.evidence_id for e in small_catalog.evidence_catalog]
        # Add the propagated caveats
        caveats = list({e.semantic_caveat_zh for e in small_catalog.evidence_catalog if e.semantic_caveat_zh})
        finding = _build_finding(
            evidence_ids=all_ids,
            classification=FindingClassification.RISK_WARNING.value,
            limitations_zh=caveats,
        )
        result = FindingValidator().validate(
            finding, small_catalog, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert result.status == ValidationStatus.VALIDATED


class TestRule3:
    def test_unknown_evidence_rejected(self, small_catalog: EvidenceCatalog) -> None:
        finding = _build_finding(
            evidence_ids=["ev_nonexistent"],
            classification=FindingClassification.DATA_QUALITY_ISSUE.value,
        )
        result = FindingValidator().validate(
            finding, small_catalog, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert result.status == ValidationStatus.REJECTED
        assert any("rule 3" in e for e in result.errors)


class TestRule4:
    def test_future_evidence_rejected(self, small_catalog: EvidenceCatalog) -> None:
        # Decision time BEFORE COT release: COT evidence is future
        finding = _build_finding(
            evidence_ids=[e.evidence_id for e in small_catalog.evidence_catalog],
            classification=FindingClassification.DATA_QUALITY_ISSUE.value,
            limitations_zh=list({e.semantic_caveat_zh for e in small_catalog.evidence_catalog if e.semantic_caveat_zh}),
        )
        # Decision time = 2024-01-10 (before COT release 1/12)
        result = FindingValidator().validate(
            finding, small_catalog, datetime(2024, 1, 10, 12, 0, tzinfo=UTC)
        )
        assert result.status == ValidationStatus.REJECTED
        assert any("rule 4" in e for e in result.errors)


class TestRule5:
    def test_quality_cap_applied(self, small_catalog: EvidenceCatalog) -> None:
        all_ids = [e.evidence_id for e in small_catalog.evidence_catalog]
        caveats = list({e.semantic_caveat_zh for e in small_catalog.evidence_catalog if e.semantic_caveat_zh})
        finding = _build_finding(
            evidence_ids=all_ids,
            classification=FindingClassification.DATA_QUALITY_ISSUE.value,
            llm_confidence=0.95,  # high
            limitations_zh=caveats,
        )
        result = FindingValidator().validate(
            finding, small_catalog, datetime(2024, 1, 15, tzinfo=UTC)
        )
        # All VALID → cap = 1.0
        assert result.capped_confidence == 0.95
        assert result.finding.final_confidence == 0.95


class TestRule6:
    def test_missing_caveats_rejected(self, small_catalog: EvidenceCatalog) -> None:
        all_ids = [e.evidence_id for e in small_catalog.evidence_catalog]
        finding = _build_finding(
            evidence_ids=all_ids,
            classification=FindingClassification.DATA_QUALITY_ISSUE.value,
            limitations_zh=[],  # empty — missing propagation
        )
        result = FindingValidator().validate(
            finding, small_catalog, datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert result.status == ValidationStatus.REJECTED
        assert any("rule 6" in e for e in result.errors)


# =============================================================================
# T-23: SSE Analysis runner
# =============================================================================


class TestAnalysisRunner:
    def test_full_pipeline_5_events(self, small_catalog: EvidenceCatalog) -> None:
        runner = AnalysisRunner()
        result = runner.run(small_catalog, datetime(2024, 1, 15, 12, 0, tzinfo=UTC))
        assert result.status.value in ("PUBLISHED", "REJECTED")
        from pit_market.llm.runner import get_run_events
        events = get_run_events(result.analysis_run_id)
        statuses = [e["data"]["status"] for e in events]
        assert "QUEUED" in statuses
        assert "EVIDENCE_READY" in statuses
        assert "LLM_RUNNING" in statuses
        assert "VALIDATING" in statuses
        # Final: PUBLISHED or REJECTED
        assert statuses[-1] in ("PUBLISHED", "REJECTED")

    def test_provider_selection(self) -> None:
        adapter = LLMAdapter(provider=LLMProvider.MOCK)
        assert isinstance(adapter._client, MockProvider)


# =============================================================================
# T-20/23 API endpoints
# =============================================================================


class TestAnalysisAPI:
    @pytest.fixture
    def client_with_panel(self, tmp_path: Path):
        silver = _silver_rows_for_cot_fred()
        panels_dir = tmp_path / "pit_panels"
        os.environ["GOLD_PANELS_DIR"] = str(panels_dir)
        result = PitPanelBuilder(silver_df=silver).build(
            datetime(2024, 1, 15, 12, 0, tzinfo=UTC),
            universe=["GLD", "QQQ"],
            output_dir=panels_dir,
        )
        with TestClient(app) as c:
            yield c, result.panel_id

    def test_evidence_endpoint(self, client_with_panel) -> None:
        c, panel_id = client_with_panel
        r = c.post(f"/v1/analyses/evidence/{panel_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["evidence_count"] == 2
        # COT semantic_warning must be in the catalog samples
        assert any("持仓" in s.get("semantic_caveat_zh", "") or "FRED" in s.get("semantic_caveat_zh", "")
                   for s in body["sample"])

    def test_analysis_start(self, client_with_panel) -> None:
        c, panel_id = client_with_panel
        r = c.post(
            "/v1/analyses",
            json={"panel_id": panel_id, "provider": "mock"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in ("PUBLISHED", "REJECTED")
        assert body["catalog_sha256"]

    def test_sse_stream_5_stages(self, client_with_panel) -> None:
        c, panel_id = client_with_panel
        r = c.post(
            "/v1/analyses",
            json={"panel_id": panel_id, "provider": "mock"},
        )
        run_id = r.json()["analysis_run_id"]
        with c.stream("GET", f"/v1/analyses/{run_id}/stream") as resp:
            statuses = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if "status" in payload:
                        statuses.append(payload["status"])
        assert "QUEUED" in statuses
        assert "EVIDENCE_READY" in statuses
        assert "LLM_RUNNING" in statuses
        assert "VALIDATING" in statuses
