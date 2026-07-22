"""Registry tests — Phase 0 gate (TODO T-03 acceptance + T-04).

Validates:
- All 12 instruments load and have required fields
- All metric field_names load and reference known availability_rule_id
- COT routing: every instrument with cftc_market_code has cot_report_type
- UNMAPPED_SYMBOL discipline #8: hard reject
- UNKNOWN_FIELD discipline: hard reject
- JSON Schemas all parse with Draft 2020-12
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pit_market.storage.registry import Registry, RegistryError

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(CONFIG_DIR)


class TestRegistryLoads:
    def test_load_succeeds(self, registry: Registry) -> None:
        assert registry is not None
        assert len(registry.instruments) > 0
        assert len(registry.metrics) > 0
        assert len(registry.availability_rules) > 0
        assert len(registry.schemas) >= 5  # observation, evidence, llm_analysis, api_slice, ui_view_state, provenance

    def test_12_instruments(self, registry: Registry) -> None:
        expected = {
            "SPY", "QQQ", "IWM",
            "GLD", "IAU", "SLV",
            "GC=F", "SI=F", "GOLD_COMEX", "SILVER_COMEX",
            "VIX", "VXN",
        }
        actual = set(registry.instruments.keys())
        assert expected.issubset(actual), f"Missing instruments: {expected - actual}"

    def test_registry_hash_stable(self, registry: Registry) -> None:
        assert len(registry.registry_hash) == 64
        # Reload and compare
        reg2 = Registry.load(CONFIG_DIR)
        assert registry.registry_hash == reg2.registry_hash


class TestInstrumentDiscipline:
    def test_cftc_instruments_have_cot_report_type(self, registry: Registry) -> None:
        """Discipline: T-05c — TFF/Disaggregated/Legacy routing required."""
        for sym, inst in registry.instruments.items():
            if inst.cftc_market_code is not None:
                assert inst.cot_report_type in {
                    "LEGACY",
                    "DISAGGREGATED",
                    "TFF",
                }, f"{sym} has cftc_market_code but invalid cot_report_type: {inst.cot_report_type}"

    def test_gold_uses_disaggregated(self, registry: Registry) -> None:
        """GOLD_COMEX and GLD/IAU must use Disaggregated COT."""
        for sym in ("GOLD_COMEX", "GLD", "IAU", "GC=F"):
            assert registry.instruments[sym].cot_report_type == "DISAGGREGATED"

    def test_yfinance_vendor_mapped(self, registry: Registry) -> None:
        for inst in registry.instruments.values():
            assert inst.vendor_symbol_yfinance, f"{inst.canonical_symbol} missing vendor_symbol_yfinance"


class TestMetricDiscipline:
    def test_all_metrics_reference_known_rule(self, registry: Registry) -> None:
        for fn, m in registry.metrics.items():
            assert m.availability_rule_id in registry.availability_rules, (
                f"{fn} references unknown availability_rule_id {m.availability_rule_id!r}"
            )

    def test_finra_short_ratio_has_semantic_warning(self, registry: Registry) -> None:
        """Discipline #7 + R-11: FINRA short_ratio must carry '非全市场' warning."""
        m = registry.metrics["flow__finra__short_ratio"]
        assert "非全市场" in m.semantic_warning or "consolidated" in m.semantic_warning.lower()

    def test_fred_fields_mark_alfred_required(self, registry: Registry) -> None:
        """Discipline #8: FRED fields must require ALFRED."""
        for fn in ("macro__fred__dgs10", "macro__fred__t10yie"):
            assert registry.metrics[fn].extra.get("requires_alfred") is True

    def test_cot_fields_mark_cot_report_type(self, registry: Registry) -> None:
        for fn in (
            "position__cftc__managed_money_net",
            "position__cftc__swap_dealer_net",
        ):
            assert registry.metrics[fn].extra.get("cot_report_type") == "DISAGGREGATED"


class TestUnmappedSymbol:
    def test_assert_canonical_symbol_rejects_unknown(self, registry: Registry) -> None:
        with pytest.raises(RegistryError, match="UNMAPPED_SYMBOL"):
            registry.assert_canonical_symbol("FAKE_SYMBOL")

    def test_assert_canonical_symbol_accepts_known(self, registry: Registry) -> None:
        registry.assert_canonical_symbol("QQQ")  # should not raise

    def test_assert_field_name_rejects_unknown(self, registry: Registry) -> None:
        with pytest.raises(RegistryError, match="UNKNOWN_FIELD"):
            registry.assert_field_name("flow__nope__bogus")

    def test_assert_field_name_accepts_known(self, registry: Registry) -> None:
        registry.assert_field_name("price__yf__close")  # should not raise


class TestSchemas:
    def test_all_schemas_loaded(self, registry: Registry) -> None:
        expected_substrings = [
            "observation",
            "evidence",
            "llm_analysis",
            "api_slice",
            "ui_view_state",
            "LLMProvenanceRunFacet",
        ]
        schema_ids = list(registry.schemas.keys())
        for sub in expected_substrings:
            assert any(sub in sid for sid in schema_ids), f"Schema {sub!r} not loaded; have {schema_ids}"


class TestAvailabilityRules:
    def test_yfinance_close_price_is_dst_safe(self, registry: Registry) -> None:
        rule = registry.get_availability_rule("yfinance_close_price")
        assert rule.raw.get("timezone_aware") is True

    def test_cftc_friday_release_minute_precision(self, registry: Registry) -> None:
        rule = registry.get_availability_rule("cftc_friday_release")
        assert rule.raw.get("precision") == "minute"
        assert rule.raw.get("release_time_et") == "15:30"

    def test_fred_rules_require_alfred(self, registry: Registry) -> None:
        for rule_id in ("fred_realtime_period", "fred_market_proxy_t_plus_1"):
            rule = registry.get_availability_rule(rule_id)
            assert rule.raw.get("uses_alfred") is True
            assert rule.raw.get("realtime_start_required") is True

    def test_finra_t_plus_1_afternoon(self, registry: Registry) -> None:
        rule = registry.get_availability_rule("finra_regsho_t_plus_1_afternoon")
        assert rule.raw.get("release_hour_et") == "14:00"
        assert rule.raw.get("max_staleness") == "2D"

    def test_etf_routes_by_issuer(self, registry: Registry) -> None:
        rule = registry.get_availability_rule("etf_shares_by_issuer")
        routes = rule.raw.get("routes", {})
        assert "state_street" in routes
        assert "blackrock" in routes
        assert routes["state_street"]["release_offset_hours"] == 22
        assert routes["blackrock"]["release_offset_hours"] == 4
