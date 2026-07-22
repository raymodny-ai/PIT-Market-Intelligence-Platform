"""Registry loaders for Instruments, Metrics, Availability Rules, and JSON Schemas.

Phase 0 deliverable (TODO T-03). Validates canonical_symbol and field_name
discipline (#8) at load time so downstream code can trust the registry.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

# =============================================================================
# Domain types
# =============================================================================


@dataclass(frozen=True)
class Instrument:
    canonical_symbol: str
    asset_class: str
    primary_market: str
    vendor_symbol_yfinance: str | None
    cftc_market_code: str | None
    cot_report_type: str | None  # LEGACY | DISAGGREGATED | TFF | None
    issuer: str | None
    related_etfs: tuple[str, ...]
    timezone: str
    display_name_zh: str
    display_name_en: str


@dataclass(frozen=True)
class Metric:
    field_name: str
    display_name_zh: str
    source_name: str
    dataset_name: str
    frequency: str
    unit: str
    availability_rule_id: str
    max_staleness: str
    forward_fill_allowed: bool
    semantic_warning: str
    feature_definition_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AvailabilityRule:
    rule_id: str
    description: str
    raw: dict[str, Any]


# =============================================================================
# Loaders
# =============================================================================


class RegistryError(Exception):
    """Raised when a registry file is missing, malformed, or inconsistent."""


class Registry:
    """In-memory registry loaded once at app startup.

    Use ``Registry.load(config_dir)`` to build. The instance exposes:
    - ``instruments: dict[str, Instrument]`` (canonical_symbol → Instrument)
    - ``metrics: dict[str, Metric]`` (field_name → Metric)
    - ``availability_rules: dict[str, AvailabilityRule]``
    - ``schemas: dict[str, dict]`` (schema_id → JSON Schema dict)
    - ``registry_hash: str`` (sha256 over all loaded files)
    """

    def __init__(
        self,
        instruments: dict[str, Instrument],
        metrics: dict[str, Metric],
        availability_rules: dict[str, AvailabilityRule],
        schemas: dict[str, dict],
        registry_hash: str,
    ) -> None:
        self.instruments = instruments
        self.metrics = metrics
        self.availability_rules = availability_rules
        self.schemas = schemas
        self.registry_hash = registry_hash

    # ----- lookups -----
    def has_instrument(self, canonical_symbol: str) -> bool:
        return canonical_symbol in self.instruments

    def has_metric(self, field_name: str) -> bool:
        return field_name in self.metrics

    def get_availability_rule(self, rule_id: str) -> AvailabilityRule:
        if rule_id not in self.availability_rules:
            raise RegistryError(f"Unknown availability_rule_id: {rule_id}")
        return self.availability_rules[rule_id]

    def get_schema(self, schema_id: str) -> dict:
        if schema_id not in self.schemas:
            raise RegistryError(f"Schema not loaded: {schema_id}")
        return self.schemas[schema_id]

    # ----- validators (used by adapters) -----
    def assert_canonical_symbol(self, symbol: str) -> None:
        """Discipline #8: hard reject of UNMAPPED_SYMBOL."""
        if symbol not in self.instruments:
            raise RegistryError(
                f"UNMAPPED_SYMBOL: {symbol!r} not in Instrument Registry. "
                f"Add to config/instruments.yaml first."
            )

    def assert_field_name(self, field_name: str) -> None:
        if field_name not in self.metrics:
            raise RegistryError(
                f"UNKNOWN_FIELD: {field_name!r} not in Metric Registry. "
                f"Add to config/metrics.yaml first."
            )

    # ----- factory -----
    @classmethod
    def load(cls, config_dir: str | Path) -> Registry:
        config_dir = Path(config_dir)
        if not config_dir.is_dir():
            raise RegistryError(f"Config dir not found: {config_dir}")

        # 1) Instruments
        instruments_raw = _load_yaml(config_dir / "instruments.yaml")
        instruments: dict[str, Instrument] = {}
        for entry in instruments_raw.get("instruments", []):
            sym = entry["canonical_symbol"]
            instruments[sym] = Instrument(
                canonical_symbol=sym,
                asset_class=entry["asset_class"],
                primary_market=entry["primary_market"],
                vendor_symbol_yfinance=entry.get("vendor_symbol_yfinance"),
                cftc_market_code=entry.get("cftc_market_code"),
                cot_report_type=entry.get("cot_report_type"),
                issuer=entry.get("issuer"),
                related_etfs=tuple(entry.get("related_etfs", [])),
                timezone=entry["timezone"],
                display_name_zh=entry.get("display_name_zh", ""),
                display_name_en=entry.get("display_name_en", ""),
            )
        instrument_version = instruments_raw.get("registry_version", "unknown")

        # 2) Metrics
        metrics_raw = _load_yaml(config_dir / "metrics.yaml")
        metrics: dict[str, Metric] = {}
        for entry in metrics_raw.get("fields", []):
            fn = entry["field_name"]
            extra = {
                k: v
                for k, v in entry.items()
                if k
                not in {
                    "field_name",
                    "display_name_zh",
                    "source_name",
                    "dataset_name",
                    "frequency",
                    "unit",
                    "availability_rule_id",
                    "max_staleness",
                    "forward_fill_allowed",
                    "semantic_warning",
                    "feature_definition_id",
                }
            }
            metrics[fn] = Metric(
                field_name=fn,
                display_name_zh=entry["display_name_zh"],
                source_name=entry["source_name"],
                dataset_name=entry["dataset_name"],
                frequency=entry["frequency"],
                unit=entry.get("unit", ""),
                availability_rule_id=entry["availability_rule_id"],
                max_staleness=entry["max_staleness"],
                forward_fill_allowed=entry.get("forward_fill_allowed", False),
                semantic_warning=entry.get("semantic_warning", ""),
                feature_definition_id=entry["feature_definition_id"],
                extra=extra,
            )
        metrics_version = metrics_raw.get("metric_registry_version", "unknown")

        # 3) Availability rules
        ar_raw = _load_yaml(config_dir / "availability_rules.yaml")
        availability_rules: dict[str, AvailabilityRule] = {}
        for rule_id, body in ar_raw.get("rules", {}).items():
            availability_rules[rule_id] = AvailabilityRule(
                rule_id=rule_id,
                description=body.get("description", ""),
                raw=body,
            )

        # 4) JSON Schemas
        schemas_dir = config_dir / "schemas"
        schemas: dict[str, dict] = {}
        if not schemas_dir.is_dir():
            raise RegistryError(f"Schemas dir not found: {schemas_dir}")
        for schema_file in sorted(schemas_dir.glob("*.schema.json")):
            with schema_file.open("r", encoding="utf-8") as f:
                schema = json.load(f)
            schema_id = schema.get("$id", schema_file.name)
            # Compile validator (raise on bad schema)
            Draft202012Validator.check_schema(schema)
            schemas[schema_id] = schema
        # Also LLMProvenanceRunFacet.json (no .schema.json suffix)
        prov_file = schemas_dir / "LLMProvenanceRunFacet.json"
        if prov_file.exists():
            with prov_file.open("r", encoding="utf-8") as f:
                schema = json.load(f)
            schema_id = schema.get("$id", prov_file.name)
            Draft202012Validator.check_schema(schema)
            schemas[schema_id] = schema

        # 5) Cross-validate: every metric.availability_rule_id must resolve
        for fn, m in metrics.items():
            if m.availability_rule_id not in availability_rules:
                raise RegistryError(
                    f"Metric {fn!r} references unknown availability_rule_id "
                    f"{m.availability_rule_id!r}"
                )

        # 6) Cross-validate: every instrument.cftc_market_code + cot_report_type
        #    (Discipline: T-05c — TFF/Disaggregated/Legacy routing)
        for sym, inst in instruments.items():
            if inst.cftc_market_code and not inst.cot_report_type:
                raise RegistryError(
                    f"Instrument {sym!r} has cftc_market_code but missing cot_report_type"
                )
            if inst.cot_report_type and inst.cot_report_type not in {
                "LEGACY",
                "DISAGGREGATED",
                "TFF",
            }:
                raise RegistryError(
                    f"Instrument {sym!r} has invalid cot_report_type: {inst.cot_report_type!r}"
                )

        # 7) Hash
        registry_hash = _hash_files(
            [
                config_dir / "instruments.yaml",
                config_dir / "metrics.yaml",
                config_dir / "availability_rules.yaml",
            ]
        )

        # Light touch summary
        import logging

        log = logging.getLogger(__name__)
        log.info(
            "Registry loaded: instruments=%d (v=%s), metrics=%d (v=%s), "
            "availability_rules=%d, schemas=%d, hash=%s",
            len(instruments),
            instrument_version,
            len(metrics),
            metrics_version,
            len(availability_rules),
            len(schemas),
            registry_hash[:12],
        )

        return cls(
            instruments=instruments,
            metrics=metrics,
            availability_rules=availability_rules,
            schemas=schemas,
            registry_hash=registry_hash,
        )


# =============================================================================
# Helpers
# =============================================================================


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RegistryError(f"YAML not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _hash_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()
