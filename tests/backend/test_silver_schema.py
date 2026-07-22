"""Silver schema + writer tests (TODO T-06 acceptance)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from pit_market.normalization.silver import (
    FillType,
    QualityStatus,
    SilverSchema,
    SilverWriter,
)
from pit_market.storage.registry import Registry

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(CONFIG_DIR)


@pytest.fixture
def writer(registry: Registry, tmp_path: Path) -> SilverWriter:
    return SilverWriter(registry=registry, silver_dir=tmp_path, parser_version="v0.3")


def _make_obs(symbol: str = "QQQ", **overrides) -> dict:
    base = {
        "observation_id": "00000000-0000-0000-0000-000000000001",
        "source_name": "yfinance",
        "dataset_name": "daily_ohlcv",
        "canonical_symbol": symbol,
        "vendor_symbol": symbol,
        "field_name": "price__yf__close",
        "value": 100.0,
        "unit": "usd",
        "frequency": "daily",
        "price_type": "RAW_CLOSE",
        "observation_time": datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
        "observation_end_time": None,
        "release_time": None,
        "available_at": datetime(2024, 1, 9, 18, 0, tzinfo=UTC),
        "valid_from": datetime(2024, 1, 8, 16, 0, tzinfo=UTC),
        "valid_to": None,
        "ingested_at": datetime(2024, 1, 8, 17, 0, tzinfo=UTC),
        "run_id": "test-run-001",
        "raw_record_hash": "abc123def456" * 5,  # >= 1 char
        "parser_version": "v0.3",
        "source_metadata_json": '{"vendor_symbol": "QQQ"}',
        "quality_status": "VALID",
        "quality_flags_json": "{}",
        "fill_type": "OBSERVED",
        "fill_source_observation_id": None,
        "fill_lag_days": None,
    }
    base.update(overrides)
    return base


class TestDisciplineCanonicalSymbol:
    def test_unmapped_symbol_rejected(self, writer: SilverWriter) -> None:
        df = pl.DataFrame([_make_obs(symbol="FAKE_QQQ")])
        result = writer.write(
            df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="test"
        )
        assert result.rejected > 0
        assert "UNMAPPED_SYMBOL" in result.rejection_reasons[0]

    def test_known_symbol_accepted(self, writer: SilverWriter) -> None:
        df = pl.DataFrame([_make_obs(symbol="QQQ")])
        result = writer.write(
            df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="test"
        )
        assert result.rejected == 0
        assert result.written == 1


class TestFillTypeDiscipline:
    def test_observed_no_source_required(self, writer: SilverWriter) -> None:
        df = pl.DataFrame([_make_obs(fill_type=FillType.OBSERVED.value)])
        result = writer.write(
            df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="test"
        )
        assert result.rejected == 0

    def test_forward_filled_requires_source_observation_id(
        self, writer: SilverWriter
    ) -> None:
        df = pl.DataFrame(
            [_make_obs(fill_type=FillType.FORWARD_FILLED.value, fill_source_observation_id=None)]
        )
        result = writer.write(
            df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="test"
        )
        assert result.rejected > 0
        assert "fill_source_observation_id" in result.rejection_reasons[0]

    def test_calendar_inferred_requires_source(self, writer: SilverWriter) -> None:
        df = pl.DataFrame(
            [_make_obs(fill_type=FillType.CALENDAR_INFERRED.value, fill_source_observation_id=None)]
        )
        result = writer.write(
            df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="test"
        )
        assert result.rejected > 0

    def test_interpolated_requires_source(self, writer: SilverWriter) -> None:
        df = pl.DataFrame(
            [_make_obs(fill_type=FillType.INTERPOLATED.value, fill_source_observation_id=None)]
        )
        result = writer.write(
            df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="test"
        )
        assert result.rejected > 0

    def test_invalid_fill_type_rejected(self, writer: SilverWriter) -> None:
        df = pl.DataFrame([_make_obs(fill_type="BOGUS")])
        result = writer.write(
            df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="test"
        )
        assert result.rejected > 0


class TestQualityStatus:
    def test_valid_accepted(self, writer: SilverWriter) -> None:
        df = pl.DataFrame([_make_obs(quality_status=QualityStatus.VALID.value)])
        result = writer.write(
            df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="test"
        )
        assert result.rejected == 0

    def test_source_throttled_accepted(self, writer: SilverWriter) -> None:
        df = pl.DataFrame([_make_obs(quality_status=QualityStatus.SOURCE_THROTTLED.value)])
        result = writer.write(
            df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="test"
        )
        assert result.rejected == 0


class TestAppendOnly:
    def test_two_writes_partition_by_available_date(
        self, writer: SilverWriter, tmp_path: Path
    ) -> None:
        df1 = pl.DataFrame(
            [_make_obs(available_at=datetime(2024, 1, 9, 18, 0, tzinfo=UTC))]
        )
        df2 = pl.DataFrame(
            [_make_obs(available_at=datetime(2024, 1, 10, 18, 0, tzinfo=UTC))]
        )
        r1 = writer.write(df1, source_name="yfinance", dataset_name="daily_ohlcv", run_id="r1")
        r2 = writer.write(df2, source_name="yfinance", dataset_name="daily_ohlcv", run_id="r2")
        assert r1.written == 1 and r2.written == 1
        # Two partition dirs created
        date_dirs = list(tmp_path.rglob("available_date=*"))
        assert len(date_dirs) == 2

    def test_vendor_symbol_preserved(self, writer: SilverWriter, tmp_path: Path) -> None:
        df = pl.DataFrame([_make_obs(canonical_symbol="QQQ", vendor_symbol="QQQ")])
        writer.write(df, source_name="yfinance", dataset_name="daily_ohlcv", run_id="r1")
        # Read back
        files = list(tmp_path.rglob("part-*.parquet"))
        assert files
        readback = pl.read_parquet(str(files[0]))
        assert "vendor_symbol" in readback.columns


class TestPanderaSchema:
    def test_schema_validates_minimal_row(self) -> None:
        df = pl.DataFrame([_make_obs()])
        SilverSchema.validate(df)  # should not raise

    def test_schema_rejects_missing_canonical_symbol(self) -> None:
        bad = _make_obs()
        del bad["canonical_symbol"]
        df = pl.DataFrame([bad])
        with pytest.raises((KeyError, ValueError, pl.exceptions.ColumnNotFoundError)):
            SilverSchema.validate(df)
