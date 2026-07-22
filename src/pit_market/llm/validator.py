"""LLM Finding validator (TODO T-22).

Enforces the 7 rules from PRD §16.3 / TODO v0.3:
1. Each finding references ≥ 1 evidence_id
2. Risk/direction findings require ≥ 2 different-domain evidence
3. evidence_id must exist in Catalog
4. All evidence available_at ≤ decision_time (PIT)
5. Quality ≠ VALID caps final_confidence
6. Source semantic warnings propagate to limitations_zh
7. Any failure → REJECTED

Discipline #7: limitations_zh MUST contain the propagated
semantic_caveat_zh from each evidence entry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from pit_market.evidence.catalog import EvidenceCatalog, EvidenceEntry

log = logging.getLogger(__name__)


class FindingClassification(StrEnum):
    RISK_WARNING = "RISK_WARNING"
    FLOW_CONFIRMATION = "FLOW_CONFIRMATION"
    POSITIONING_EXTREME = "POSITIONING_EXTREME"
    MACRO_REGIME = "MACRO_REGIME"
    VOLATILITY_REGIME = "VOLATILITY_REGIME"
    DATA_QUALITY_ISSUE = "DATA_QUALITY_ISSUE"


class CausalLanguageLevel(StrEnum):
    ASSOCIATIVE_ONLY = "ASSOCIATIVE_ONLY"
    DESCRIPTIVE = "DESCRIPTIVE"


class ValidationStatus(StrEnum):
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


@dataclass
class Finding:
    finding_id: str
    title_zh: str
    claim_zh: str
    classification: str
    support_type: str
    causal_language_level: str
    llm_confidence: float
    final_confidence: float
    evidence_ids: list[str]
    limitations_zh: list[str]
    model: str = ""
    prompt_version: str = ""


@dataclass
class ValidationResult:
    status: ValidationStatus
    finding: Finding | None
    errors: list[str] = field(default_factory=list)
    capped_confidence: float = 0.0


# Quality → confidence cap (T-22 rule 5)
QUALITY_CAP = {
    "VALID": 1.0,
    "DEGRADED": 0.75,
    "STALE": 0.5,
    "INFERRED_AVAILABILITY": 0.6,
    "PARTIAL": 0.4,
    "REJECTED": 0.0,
    "SOURCE_FAILED": 0.0,
    "SOURCE_THROTTLED": 0.5,
}

# Classifications that require ≥ 2 different-domain evidence
RISK_CLASSIFICATIONS = {
    FindingClassification.RISK_WARNING,
    FindingClassification.FLOW_CONFIRMATION,
    FindingClassification.MACRO_REGIME,
}


class FindingValidator:
    """7-rule validator (T-22)."""

    def validate(
        self,
        finding: Finding,
        catalog: EvidenceCatalog,
        decision_time: datetime,
    ) -> ValidationResult:
        errors: list[str] = []
        evidence_by_id: dict[str, EvidenceEntry] = {
            e.evidence_id: e for e in catalog.evidence_catalog
        }

        # Rule 1: ≥ 1 evidence
        if not finding.evidence_ids:
            errors.append("rule 1: finding must reference ≥ 1 evidence_id")

        # Rule 3: all evidence_ids exist in catalog
        missing = [eid for eid in finding.evidence_ids if eid not in evidence_by_id]
        if missing:
            errors.append(f"rule 3: evidence_ids not in catalog: {missing}")

        # Rule 4: PIT — all available_at <= decision_time
        pit_violations = []
        for eid in finding.evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev and ev.available_at > decision_time:
                pit_violations.append(eid)
        if pit_violations:
            errors.append(
                f"rule 4: PIT violation — evidence not yet available: {pit_violations}"
            )

        # Rule 2: risk classifications require ≥ 2 different-domain evidence
        if finding.classification in {c.value for c in RISK_CLASSIFICATIONS}:
            domains = {
                evidence_by_id[eid].field_name.split("__")[1] if eid in evidence_by_id else None
                for eid in finding.evidence_ids
            }
            domains.discard(None)
            if len(domains) < 2:
                errors.append(
                    f"rule 2: {finding.classification} requires ≥ 2 different-domain evidence "
                    f"(got {len(domains)})"
                )

        # Rule 5: confidence cap by worst evidence quality
        worst_quality = "VALID"
        quality_order = ["REJECTED", "SOURCE_FAILED", "PARTIAL", "STALE", "INFERRED_AVAILABILITY", "DEGRADED", "VALID"]
        for eid in finding.evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev and quality_order.index(ev.quality_status) < quality_order.index(worst_quality):
                worst_quality = ev.quality_status
        cap = QUALITY_CAP.get(worst_quality, 0.5)
        capped_confidence = min(finding.llm_confidence, cap)

        # Rule 6: limitations_zh must include each evidence's semantic_caveat_zh
        required_caveats: set[str] = set()
        for eid in finding.evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev and ev.semantic_caveat_zh and ev.semantic_caveat_zh not in finding.limitations_zh:
                required_caveats.add(ev.semantic_caveat_zh)
        if required_caveats:
            errors.append(
                f"rule 6: limitations_zh missing propagated caveats: {required_caveats}"
            )
        # else: all propagated

        # Rule 7: any failure → REJECTED
        status = ValidationStatus.REJECTED if errors else ValidationStatus.VALIDATED

        if status == ValidationStatus.VALIDATED:
            finding.final_confidence = capped_confidence
            return ValidationResult(
                status=status, finding=finding, capped_confidence=capped_confidence
            )
        return ValidationResult(
            status=status, finding=None, errors=errors, capped_confidence=capped_confidence
        )
