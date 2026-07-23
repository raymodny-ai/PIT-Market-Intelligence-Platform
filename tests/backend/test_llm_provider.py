"""Tests for the OpenAI-compatible LLM provider path (DeepSeek, OpenAI)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from openai import OpenAI

from pit_market.evidence.catalog import EvidenceCatalog, EvidenceEntry, FieldState
from pit_market.llm.adapter import (
    LLMAdapter,
    LLMProvider,
    OpenAICompatProvider,
)


# ----------------------------------------------------------------------
# LLMAdapter factory
# ----------------------------------------------------------------------


class TestLLMAdapterFactory:
    def test_factory_mock_default(self) -> None:
        adapter = LLMAdapter()
        # MOCK path doesn't need a key; smoke-test analyze runs without network.
        catalog = _empty_catalog()
        result = adapter.analyze(catalog)
        assert "finding_id" in result
        assert result["classification"] in {
            c.value for c in __import__("pit_market.llm.validator", fromlist=["FindingClassification"]).FindingClassification
        }

    def test_factory_openai_requires_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        adapter = LLMAdapter(provider=LLMProvider.OPENAI)
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            adapter.analyze(_empty_catalog())

    def test_factory_deepseek_requires_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        adapter = LLMAdapter(provider=LLMProvider.DEEPSEEK)
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            adapter.analyze(_empty_catalog())

    def test_factory_deepseek_reads_env_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
        # Build the adapter (no analyze yet — we just check the key was loaded).
        adapter = LLMAdapter(provider=LLMProvider.DEEPSEEK)
        assert adapter._client._api_key == "sk-test-deepseek"
        assert adapter._client._base_url == "https://api.deepseek.com"
        assert adapter._client._model == "deepseek-chat"

    def test_factory_deepseek_default_model_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        adapter = LLMAdapter(provider=LLMProvider.DEEPSEEK, model="deepseek-reasoner")
        assert adapter._client._model == "deepseek-reasoner"

    def test_factory_openai_default_url_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        adapter = LLMAdapter(provider=LLMProvider.OPENAI)
        # OpenAI default: base_url=None so the SDK falls back to the official endpoint.
        assert adapter._client._base_url is None
        assert adapter._client._model == "gpt-4o"


# ----------------------------------------------------------------------
# OpenAICompatProvider.analyze() — mock the SDK to assert payload shape
# ----------------------------------------------------------------------


def _ok_response(payload: dict) -> MagicMock:
    """Build a MagicMock that quacks like openai's chat completion response."""
    msg = MagicMock()
    msg.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


class TestOpenAICompatProvider:
    def test_analyze_calls_openai_sdk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_payload = {
            "finding_id": "11111111-1111-1111-1111-111111111111",
            "title_zh": "示例",
            "claim_zh": "可能存在风险",
            "classification": "RISK_WARNING",
            "support_type": "MULTI_FACTOR_CONFIRMATION",
            "causal_language_level": "ASSOCIATIVE_ONLY",
            "llm_confidence": 0.7,
            "evidence_ids": ["ev-1"],
            "limitations_zh": ["数据延迟"],
        }
        with patch("openai.OpenAI") as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.chat.completions.create.return_value = _ok_response(fake_payload)
            provider = OpenAICompatProvider(
                api_key="sk-test",
                model="deepseek-chat",
                base_url="https://api.deepseek.com",
                provider_label="deepseek",
            )
            result = provider.analyze(_empty_catalog(), "user prompt here")
            # SDK call signature:
            call = mock_instance.chat.completions.create.call_args
            assert call.kwargs["model"] == "deepseek-chat"
            messages = call.kwargs["messages"]
            assert messages[0]["role"] == "system"
            assert "evidence_ids" in messages[0]["content"]
            assert messages[1]["content"] == "user prompt here"
            assert call.kwargs["response_format"] == {"type": "json_object"}
            # Parsed payload returned
            assert result == fake_payload

    def test_analyze_raises_on_non_json_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with patch("openai.OpenAI") as MockClient:
            mock_instance = MockClient.return_value
            msg = MagicMock()
            msg.content = "not json at all"
            choice = MagicMock()
            choice.message = msg
            response = MagicMock()
            response.choices = [choice]
            mock_instance.chat.completions.create.return_value = response
            provider = OpenAICompatProvider(
                api_key="sk-test",
                model="deepseek-chat",
                base_url="https://api.deepseek.com",
                provider_label="deepseek",
            )
            with pytest.raises(RuntimeError, match="non-JSON content"):
                provider.analyze(_empty_catalog())

    def test_analyze_missing_key_raises_immediately(self) -> None:
        provider = OpenAICompatProvider(
            api_key=None,
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
            provider_label="deepseek",
        )
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            provider.analyze(_empty_catalog())


# ----------------------------------------------------------------------
# Live integration test (skipped unless DEEPSEEK_API_KEY is set AND
# the user explicitly opts in via PIT_LIVE_LLM=1 to keep CI deterministic).
# ----------------------------------------------------------------------


@pytest.mark.skipif(
    "DEEPSEEK_API_KEY" not in __import__("os").environ
    or __import__("os").environ.get("PIT_LIVE_LLM") != "1",
    reason="Live DeepSeek test — set PIT_LIVE_LLM=1 with DEEPSEEK_API_KEY to run",
)
class TestDeepSeekLive:
    def test_real_analyze_returns_valid_finding_shape(self) -> None:
        # Use an empty catalog — the LLM call itself just needs the prompt to
        # round-trip. Real schemas go through EvidenceCatalogBuilder in
        # /v1/analyses (covered by integration tests in test_phase3_llm.py).
        adapter = LLMAdapter(provider=LLMProvider.DEEPSEEK)
        catalog = _empty_catalog()
        result = adapter.analyze(catalog, user_prompt="ping — please return a valid Finding JSON")
        assert isinstance(result, dict)
        assert "finding_id" in result
        assert "title_zh" in result
        assert "claim_zh" in result
        assert "evidence_ids" in result
        assert isinstance(result["evidence_ids"], list)
        assert 0.0 <= float(result["llm_confidence"]) <= 1.0


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _empty_catalog() -> EvidenceCatalog:
    return EvidenceCatalog(
        catalog_id="cat-empty",
        pit_panel_id="pit-empty",
        catalog_sha256="0" * 64,
        decision_time=__import__("datetime").datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        evidence_catalog=[],
    )


def _single_evidence_catalog() -> EvidenceCatalog:
    return EvidenceCatalog(
        catalog_id="cat-test",
        pit_panel_id="pit-test",
        catalog_sha256="0" * 64,
        decision_time=__import__("datetime").datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        evidence_catalog=[
            EvidenceEntry(
                evidence_id="ev-spy-1",
                symbol="SPY",
                field_name="price_volume__close",
                value=450.0,
                state=FieldState.NEUTRAL,
                available_at=__import__("datetime").datetime.fromisoformat(
                    "2025-12-31T21:00:00+00:00"
                ),
                age_hours=3.0,
                semantic_caveat_zh="价格采样间隔 1 天",
            )
        ],
    )