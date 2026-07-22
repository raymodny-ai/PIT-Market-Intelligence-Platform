"""Availability Resolver tests (TODO T-07 acceptance)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pit_market.normalization.resolver import (
    AvailabilityResolver,
    AvailabilityType,
)
from pit_market.storage.registry import Registry

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(CONFIG_DIR)


@pytest.fixture
def resolver(registry: Registry) -> AvailabilityResolver:
    return AvailabilityResolver(registry)


# =============================================================================
# Priority 1: official release time
# =============================================================================


class TestOfficialRelease:
    def test_release_time_used_when_provided(
        self, resolver: AvailabilityResolver
    ) -> None:
        obs = datetime(2024, 1, 9, 16, 0, tzinfo=UTC)
        release = datetime(2024, 1, 12, 15, 30, tzinfo=UTC)
        r = resolver.resolve("position__cftc__managed_money_net", obs, source_release_time=release)
        assert r.availability_type == AvailabilityType.OFFICIAL_RELEASE
        assert r.available_at == release


# =============================================================================
# CFTC Friday 15:30 ET
# =============================================================================


class TestCftcFridayRelease:
    def test_tuesday_to_friday_15_30_et(self, resolver: AvailabilityResolver) -> None:
        # 2024-01-09 (Tue) → Friday 2024-01-12 15:30 ET
        obs = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
        r = resolver.resolve("position__cftc__managed_money_net", obs)
        assert r.availability_type == AvailabilityType.RELEASE_CALENDAR
        # 15:30 ET = 20:30 UTC (EST) in January
        assert r.available_at == datetime(2024, 1, 12, 20, 30, tzinfo=UTC)

    def test_dst_safe_summer(self, resolver: AvailabilityResolver) -> None:
        # 2024-07-09 (Tue) → Friday 2024-07-12 15:30 ET (EDT = UTC-4)
        obs = datetime(2024, 7, 9, 21, 0, tzinfo=UTC)
        r = resolver.resolve("position__cftc__managed_money_net", obs)
        assert r.available_at == datetime(2024, 7, 12, 19, 30, tzinfo=UTC)

    def test_holiday_friday_shifts_to_monday(self, resolver: AvailabilityResolver) -> None:
        # 2026-07-04 is Saturday; NYSE observes Independence Day on Fri 2026-07-03.
        # Tuesday 2026-06-30 → Friday 2026-07-03 is a holiday → Mon 2026-07-06.
        obs = datetime(2026, 6, 30, 21, 0, tzinfo=UTC)
        r = resolver.resolve("position__cftc__managed_money_net", obs)
        assert r.available_at.date() == datetime(2026, 7, 6).date()


# =============================================================================
# FINRA T+1 14:00 ET
# =============================================================================


class TestFinraTPlus1:
    def test_monday_to_tuesday_14_et(self, resolver: AvailabilityResolver) -> None:
        obs = datetime(2024, 1, 8, 16, 0, tzinfo=UTC)
        r = resolver.resolve("flow__finra__short_volume", obs)
        assert r.availability_type == AvailabilityType.CONSERVATIVE_RULE
        # 14:00 ET (EST) = 19:00 UTC
        assert r.available_at == datetime(2024, 1, 9, 19, 0, tzinfo=UTC)

    def test_friday_to_tuesday_after_mlk(self, resolver: AvailabilityResolver) -> None:
        obs = datetime(2024, 1, 12, 16, 0, tzinfo=UTC)
        r = resolver.resolve("flow__finra__short_volume", obs)
        # Mon 2024-01-15 is MLK Day → next biz = Tue 2024-01-16 14:00 ET
        assert r.available_at.date() == datetime(2024, 1, 16).date()


# =============================================================================
# FRED market proxy
# =============================================================================


class TestFredMarketProxy:
    def test_t_plus_1_18_et(self, resolver: AvailabilityResolver) -> None:
        # VIX on 2024-01-08 close (16:00 UTC) → T+1 18:00 ET = 2024-01-09 23:00 UTC
        obs = datetime(2024, 1, 8, 16, 0, tzinfo=UTC)
        r = resolver.resolve("macro__fred__vixcls", obs)
        assert r.available_at.date() == datetime(2024, 1, 9).date()
        assert r.available_at.hour == 23  # 18:00 EST = 23:00 UTC


# =============================================================================
# Yahoo close final 18:00 ET same day
# =============================================================================


class TestYfinanceClose:
    def test_obs_18_et_same_day(self, resolver: AvailabilityResolver) -> None:
        # obs_time UTC 16:00 on 2024-01-08 → ET 11:00 same day
        # rule: observation_time_et=16:00 + 2h offset → 18:00 ET = 23:00 UTC
        obs = datetime(2024, 1, 8, 16, 0, tzinfo=UTC)
        r = resolver.resolve("price__yf__close", obs)
        assert r.available_at.date() == datetime(2024, 1, 8).date()
        # 18:00 ET (EST) = 23:00 UTC
        assert r.available_at.hour == 23


# =============================================================================
# Unknown field
# =============================================================================


class TestUnknownField:
    def test_unknown_field_raises(self, resolver: AvailabilityResolver) -> None:
        with pytest.raises(ValueError, match="Unknown field_name"):
            resolver.resolve("nonexistent__field", datetime.now(UTC))
