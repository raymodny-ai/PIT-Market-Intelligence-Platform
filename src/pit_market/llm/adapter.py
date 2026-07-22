"""LLM Adapter (TODO T-21).

Provider-agnostic interface for structured LLM analysis.

Real providers (OpenAI, Gemini, Local) are stubbed; tests use a
``MockProvider`` that returns pre-canned Finding dicts. The interface
is what the rest of the system relies on; provider swap is mechanical.

Discipline: prompt templates live in ``config/llm_prompts.yaml`` (created
in T-21 follow-up). The system prompt forces:
- evidence_ids (array, at least 1)
- causal_language_level: ASSOCIATIVE_ONLY
- limitations_zh (array)
- llm_confidence and final_confidence reported separately
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict
from enum import StrEnum
from typing import Any, Protocol

from pit_market.evidence.catalog import EvidenceCatalog
from pit_market.llm.validator import CausalLanguageLevel

log = logging.getLogger(__name__)


class LLMProvider(StrEnum):
    OPENAI = "openai"
    GEMINI = "gemini"
    LOCAL = "local"
    MOCK = "mock"


SYSTEM_PROMPT = """You are a market intelligence analyst. You will receive an
Evidence Catalog (a list of PIT-validated observations). You must produce
a single Finding in JSON with these REQUIRED fields:

- finding_id: a uuid4 string
- title_zh: short title in Chinese
- claim_zh: claim in Chinese using ASSOCIATIVE_ONLY language ("可能", "一致于", "需要确认")
- classification: one of [RISK_WARNING, FLOW_CONFIRMATION, POSITIONING_EXTREME,
  MACRO_REGIME, VOLATILITY_REGIME, DATA_QUALITY_ISSUE]
- support_type: SINGLE_FACTOR | MULTI_FACTOR_CONFIRMATION | REVISION | NO_EVIDENCE
- causal_language_level: ASSOCIATIVE_ONLY (default) or DESCRIPTIVE
- llm_confidence: 0.0-1.0 (your pre-validation confidence)
- evidence_ids: list of evidence_id strings from the catalog
- limitations_zh: list of Chinese strings — must include each evidence's
  semantic_caveat_zh verbatim

DO NOT:
- fabricate data, sources, dates, or causal conclusions
- use imperative or definitive language ("X will happen")
- reference evidence_ids not in the catalog
"""


class LLMClient(Protocol):
    def analyze(
        self,
        catalog: EvidenceCatalog,
        user_prompt: str = "",
    ) -> dict[str, Any]: ...


class MockProvider:
    """Deterministic mock — used in tests and CI."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self._response = response or {}

    def analyze(
        self,
        catalog: EvidenceCatalog,
        user_prompt: str = "",
    ) -> dict[str, Any]:
        if self._response:
            return self._response
        # Default: pick first 2 evidence entries from different domains
        domains_seen: set[str] = set()
        chosen: list[str] = []
        for e in catalog.evidence_catalog:
            domain = e.field_name.split("__")[1] if "__" in e.field_name else e.field_name
            if domain not in domains_seen:
                chosen.append(e.evidence_id)
                domains_seen.add(domain)
            if len(chosen) >= 2:
                break
        caveats = list({
            e.semantic_caveat_zh
            for e in catalog.evidence_catalog
            if e.semantic_caveat_zh
        })
        return {
            "finding_id": str(uuid.uuid4()),
            "title_zh": "示例 Finding",
            "claim_zh": "可能存在跨因子风险信号,需要确认。",
            "classification": "RISK_WARNING",
            "support_type": "MULTI_FACTOR_CONFIRMATION",
            "causal_language_level": CausalLanguageLevel.ASSOCIATIVE_ONLY.value,
            "llm_confidence": 0.7,
            "evidence_ids": chosen,
            "limitations_zh": caveats,
        }


class OpenAIProvider:
    """OpenAI stub — real impl in production with API key."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o") -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._model = model

    def analyze(
        self,
        catalog: EvidenceCatalog,
        user_prompt: str = "",
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        # Real call would POST to /v1/chat/completions with response_format={type:json_schema}.
        # Phase 3 ships a stub; real network code is T-21 follow-up.
        raise NotImplementedError("OpenAIProvider real network call not implemented in T-21; use MockProvider in tests")


class LLMAdapter:
    """Top-level adapter — picks provider, builds prompt, returns Finding dict."""

    def __init__(
        self,
        provider: LLMProvider = LLMProvider.MOCK,
        model: str = "gpt-4o",
        api_key: str | None = None,
    ) -> None:
        if provider == LLMProvider.MOCK:
            self._client: LLMClient = MockProvider()
        elif provider == LLMProvider.OPENAI:
            self._client = OpenAIProvider(api_key=api_key, model=model)
        elif provider in (LLMProvider.GEMINI, LLMProvider.LOCAL):
            raise NotImplementedError(f"{provider.value} provider ships in T-21 follow-up")
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def analyze(
        self,
        catalog: EvidenceCatalog,
        user_prompt: str = "",
    ) -> dict[str, Any]:
        # Build user_prompt if not given
        if not user_prompt:
            user_prompt = (
                "Evidence Catalog:\n"
                + json.dumps([asdict(e) for e in catalog.evidence_catalog[:50]], default=str)
                + "\n\nProduce a Finding per the system prompt."
            )
        # Inject system prompt in the body for stub
        full_prompt = f"<<system>>\n{SYSTEM_PROMPT}\n<<user>>\n{user_prompt}"
        return self._client.analyze(catalog, full_prompt)
