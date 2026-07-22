"""Trading calendar tests — Phase 0 gate (TODO T-04 acceptance).

Validates NYSE calendar for 2024-2026. Each asserted date is taken from
the official NYSE trading hours page (https://www.nyse.com/markets/hours-calendars).
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from pit_market.data.trading_calendar import (
    add_business_days,
    holidays_in_range,
    is_trading_day,
    next_trading_day,
    previous_trading_day,
    trading_days_between,
)

# =============================================================================
# Closed days (holidays) — NYSE 2024-2026
# Source: https://www.nyse.com/markets/hours-calendars
# =============================================================================

# 2024 NYSE holidays (full-day closures)
NYSE_CLOSED_2024 = [
    date(2024, 1, 1),    # New Year's Day (observed Monday)
    date(2024, 1, 15),   # Martin Luther King Jr. Day
    date(2024, 2, 19),   # Presidents' Day
    date(2024, 3, 29),   # Good Friday
    date(2024, 5, 27),   # Memorial Day
    date(2024, 6, 19),   # Juneteenth
    date(2024, 7, 4),    # Independence Day
    date(2024, 9, 2),    # Labor Day
    date(2024, 11, 28),  # Thanksgiving Day
    date(2024, 12, 25),  # Christmas Day
]

# 2025 NYSE holidays
# Note: 2025-01-09 added — national day of mourning for President Jimmy Carter
NYSE_CLOSED_2025 = [
    date(2025, 1, 1),    # New Year's Day
    date(2025, 1, 9),    # National Day of Mourning (Jimmy Carter)
    date(2025, 1, 20),   # MLK Day
    date(2025, 2, 17),   # Presidents' Day
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 26),   # Memorial Day
    date(2025, 6, 19),   # Juneteenth
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
]

# 2026 NYSE holidays (as published; update if NYSE revises)
NYSE_CLOSED_2026 = [
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed, since 7/4 is Saturday)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
]


# =============================================================================
# Core: is_trading_day
# =============================================================================


class TestIsTradingDay:
    @pytest.mark.parametrize("d", NYSE_CLOSED_2024 + NYSE_CLOSED_2025 + NYSE_CLOSED_2026)
    def test_closed_days_not_trading(self, d: date) -> None:
        assert is_trading_day(d) is False, f"{d} should be closed (NYSE holiday)"

    @pytest.mark.parametrize(
        "d",
        [
            date(2024, 1, 2),   # First trading day after New Year
            date(2024, 7, 5),   # Friday after Independence Day
            date(2024, 12, 24), # Christmas Eve (NOT a holiday, but early close)
            date(2024, 12, 31), # New Year's Eve (NOT a holiday, but early close)
            date(2025, 1, 2),
            date(2025, 7, 7),   # Monday after July 4 (Friday)
            date(2025, 11, 28), # Friday after Thanksgiving
            date(2026, 1, 2),
            date(2026, 7, 6),   # Monday after July 4 (observed Friday)
            date(2026, 12, 24),
        ],
    )
    def test_open_days_are_trading(self, d: date) -> None:
        assert is_trading_day(d) is True, f"{d} should be an open trading day"

    @pytest.mark.parametrize(
        "d",
        [
            date(2024, 1, 6),   # Saturday
            date(2024, 1, 7),   # Sunday
            date(2024, 7, 6),   # Saturday
            date(2025, 4, 19),  # Saturday
            date(2025, 4, 20),  # Sunday
            date(2026, 4, 4),   # Saturday
            date(2026, 4, 5),   # Sunday
        ],
    )
    def test_weekends_not_trading(self, d: date) -> None:
        assert is_trading_day(d) is False, f"{d} is a weekend, should not be trading"

    def test_accepts_string_input(self) -> None:
        assert is_trading_day("2024-12-25") is False
        assert is_trading_day("2024-12-26") is True

    def test_accepts_datetime_input(self) -> None:
        assert is_trading_day(datetime(2024, 12, 25, 14, 30)) is False
        assert is_trading_day(datetime(2024, 12, 26, 9, 0)) is True


# =============================================================================
# Edge cases: previous / next trading day
# =============================================================================


class TestPreviousNextTradingDay:
    def test_saturday_previous(self) -> None:
        # Saturday 2024-01-06 → previous trading day = Friday 2024-01-05
        assert previous_trading_day(date(2024, 1, 6)) == date(2024, 1, 5)

    def test_sunday_previous(self) -> None:
        # Sunday 2024-01-07 → Friday 2024-01-05
        assert previous_trading_day(date(2024, 1, 7)) == date(2024, 1, 5)

    def test_monday_previous(self) -> None:
        # Monday 2024-01-08 → Friday 2024-01-05
        assert previous_trading_day(date(2024, 1, 8)) == date(2024, 1, 5)

    def test_friday_previous(self) -> None:
        # Friday 2024-01-12 → Thursday 2024-01-11
        assert previous_trading_day(date(2024, 1, 12)) == date(2024, 1, 11)

    def test_christmas_previous(self) -> None:
        # Christmas Day 2024-12-25 (Wed) → Tuesday 2024-12-24
        # Christmas Eve 2024-12-24 is an early close, still a trading day
        assert previous_trading_day(date(2024, 12, 25)) == date(2024, 12, 24)

    def test_new_year_next(self) -> None:
        # New Year 2025-01-01 (Wed) → next trading day = Thursday 2025-01-02
        assert next_trading_day(date(2025, 1, 1)) == date(2025, 1, 2)

    def test_saturday_next(self) -> None:
        # Saturday 2024-01-06 → Monday 2024-01-08
        assert next_trading_day(date(2024, 1, 6)) == date(2024, 1, 8)

    def test_friday_next(self) -> None:
        # Friday 2024-07-05 → Monday 2024-07-08
        assert next_trading_day(date(2024, 7, 5)) == date(2024, 7, 8)

    def test_good_friday_next(self) -> None:
        # Good Friday 2024-03-29 → Monday 2024-04-01
        assert next_trading_day(date(2024, 3, 29)) == date(2024, 4, 1)

    def test_thanksgiving_friday(self) -> None:
        # Thanksgiving 2024-11-28 (Thu) → Friday 2024-11-29
        assert next_trading_day(date(2024, 11, 28)) == date(2024, 11, 29)


# =============================================================================
# DST safety — tests the 2024 and 2025 DST transitions
# =============================================================================


class TestDSTSafety:
    def test_dst_spring_forward_week(self) -> None:
        # DST 2024 starts 2024-03-10 (Sun). Mon 2024-03-11 should be a normal trading day.
        assert is_trading_day(date(2024, 3, 11)) is True
        assert is_trading_day(date(2024, 3, 8)) is True  # Friday before DST

    def test_dst_fall_back_week(self) -> None:
        # DST 2024 ends 2024-11-03 (Sun). Mon 2024-11-04 should be a normal trading day.
        assert is_trading_day(date(2024, 11, 4)) is True
        assert is_trading_day(date(2024, 11, 1)) is True  # Friday before fall back


# =============================================================================
# trading_days_between
# =============================================================================


class TestTradingDaysBetween:
    def test_one_week(self) -> None:
        # Mon 2024-01-08 to Fri 2024-01-12: 5 trading days
        days = trading_days_between(date(2024, 1, 8), date(2024, 1, 12))
        assert len(days) == 5
        assert days[0] == date(2024, 1, 8)
        assert days[-1] == date(2024, 1, 12)

    def test_with_weekend(self) -> None:
        # Fri 2024-01-05 to Mon 2024-01-08: 2 trading days (Fri + Mon)
        days = trading_days_between(date(2024, 1, 5), date(2024, 1, 8))
        assert len(days) == 2

    def test_with_holiday(self) -> None:
        # Wed 2024-07-03 to Mon 2024-07-08: holiday on 7/4 (Thu), early close 7/4
        # Trading days: 7/3 (Wed), 7/5 (Fri), 7/8 (Mon) = 3 days
        days = trading_days_between(date(2024, 7, 3), date(2024, 7, 8))
        assert len(days) == 3
        assert date(2024, 7, 4) not in days  # Independence Day

    def test_inverted_range(self) -> None:
        # start > end → empty
        assert trading_days_between(date(2024, 1, 12), date(2024, 1, 8)) == []

    def test_single_day(self) -> None:
        # start == end (trading day)
        days = trading_days_between(date(2024, 1, 8), date(2024, 1, 8))
        assert days == [date(2024, 1, 8)]

    def test_single_closed_day(self) -> None:
        # start == end (closed)
        days = trading_days_between(date(2024, 12, 25), date(2024, 12, 25))
        assert days == []


# =============================================================================
# add_business_days — used by FINRA T+1 / CFTC etc.
# =============================================================================


class TestAddBusinessDays:
    def test_t_plus_1_weekday(self) -> None:
        # Mon 2024-01-08 + 1 business day = Tue 2024-01-09
        assert add_business_days(date(2024, 1, 8), 1) == date(2024, 1, 9)

    def test_t_plus_1_friday(self) -> None:
        # Fri 2024-01-12 + 1 business day = Mon 2024-01-15 (but MLK Day!) = Tue 2024-01-16
        assert add_business_days(date(2024, 1, 12), 1) == date(2024, 1, 16)

    def test_t_plus_1_cross_weekend(self) -> None:
        # Thu 2024-01-11 + 1 business day = Fri 2024-01-12
        assert add_business_days(date(2024, 1, 11), 1) == date(2024, 1, 12)

    def test_t_plus_1_cross_christmas(self) -> None:
        # Tue 2024-12-24 + 1 business day = Thu 2024-12-26 (25th is Christmas, 24th is early close but trading)
        assert add_business_days(date(2024, 12, 24), 1) == date(2024, 12, 26)

    def test_t_plus_2(self) -> None:
        # Mon 2024-01-08 + 2 business days = Wed 2024-01-10
        assert add_business_days(date(2024, 1, 8), 2) == date(2024, 1, 10)

    def test_t_minus_1(self) -> None:
        # Wed 2024-01-10 - 1 business day = Tue 2024-01-09
        assert add_business_days(date(2024, 1, 10), -1) == date(2024, 1, 9)


# =============================================================================
# Comprehensive 2024-2026 audit — must match NYSE official 100%
# =============================================================================


class TestComprehensiveAudit:
    def test_2024_full_year(self) -> None:
        """Assert every 2024 weekday is correctly classified."""
        from datetime import timedelta

        start = date(2024, 1, 1)
        end = date(2024, 12, 31)
        cur = start
        mismatches: list[tuple[date, bool, bool]] = []
        while cur <= end:
            if cur.weekday() < 5:  # weekday
                expected = cur not in NYSE_CLOSED_2024
                actual = is_trading_day(cur)
                if actual != expected:
                    mismatches.append((cur, expected, actual))
            cur += timedelta(days=1)
        assert not mismatches, f"2024 calendar mismatches: {mismatches}"

    def test_2025_full_year(self) -> None:
        from datetime import timedelta

        start = date(2025, 1, 1)
        end = date(2025, 12, 31)
        cur = start
        mismatches: list[tuple[date, bool, bool]] = []
        while cur <= end:
            if cur.weekday() < 5:
                expected = cur not in NYSE_CLOSED_2025
                actual = is_trading_day(cur)
                if actual != expected:
                    mismatches.append((cur, expected, actual))
            cur += timedelta(days=1)
        assert not mismatches, f"2025 calendar mismatches: {mismatches}"

    def test_2026_full_year(self) -> None:
        from datetime import timedelta

        start = date(2026, 1, 1)
        end = date(2026, 12, 31)
        cur = start
        mismatches: list[tuple[date, bool, bool]] = []
        while cur <= end:
            if cur.weekday() < 5:
                expected = cur not in NYSE_CLOSED_2026
                actual = is_trading_day(cur)
                if actual != expected:
                    mismatches.append((cur, expected, actual))
            cur += timedelta(days=1)
        assert not mismatches, f"2026 calendar mismatches: {mismatches}"


# =============================================================================
# Holidays debug helper
# =============================================================================


class TestHolidaysHelper:
    def test_holidays_in_range_2024(self) -> None:
        h = holidays_in_range(date(2024, 1, 1), date(2024, 12, 31))
        # All NYSE_CLOSED_2024 entries that are weekdays should appear
        weekday_holidays = [d for d in NYSE_CLOSED_2024 if d.weekday() < 5]
        for d in weekday_holidays:
            assert d in h, f"Missing holiday in helper output: {d}"
