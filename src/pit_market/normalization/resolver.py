"""Availability Resolver (TODO T-07).

Determines ``available_at`` for a Silver observation from a metric's
availability rule. Five-level priority (PRD §9.3):

  1. Official release time (release_time in source metadata)
  2. Release calendar (config/availability_rules.yaml — encoded in rule)
  3. Conservative configured rule
  4. File detection time
  5. Actual fetch time (ingested_at)

For Phase 1 we implement #2 + #3 (rule-driven) plus a generic fallback to
#5 (ingested_at). #1 is sourced from upstream source metadata when present
(e.g. ALFRED vintage dates; CFTC's 15:30 ET Friday rule already encodes it).
#4 is a stretch goal for Phase 2.

Discipline #8: ``available_at`` MUST be TIMESTAMPTZ minute precision.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from pit_market.data.trading_calendar import (
    add_business_days,
    is_trading_day,
    next_trading_day,
)
from pit_market.storage.registry import AvailabilityRule, Registry

log = logging.getLogger(__name__)


# US/Eastern timezone (DST aware)
try:
    from zoneinfo import ZoneInfo
    ET: Any = ZoneInfo("America/New_York")
except ImportError:  # pragma: no cover
    ET = timezone(timedelta(hours=-5))


class AvailabilityType(StrEnum):
    OFFICIAL_RELEASE = "OFFICIAL_RELEASE"
    RELEASE_CALENDAR = "RELEASE_CALENDAR"
    CONSERVATIVE_RULE = "CONSERVATIVE_RULE"
    FILE_DETECTION = "FILE_DETECTION"
    FETCH_TIME = "FETCH_TIME"


@dataclass
class ResolvedAvailability:
    available_at: datetime
    availability_type: AvailabilityType
    rule_id: str
    tz_aware: bool


class AvailabilityResolver:
    """Resolve available_at for a metric and observation."""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def resolve(
        self,
        field_name: str,
        observation_time: datetime,
        source_release_time: datetime | None = None,
        ingested_at: datetime | None = None,
    ) -> ResolvedAvailability:
        """Resolve available_at for a given field + observation.

        Args:
            field_name: registered metric field name
            observation_time: when the data was actually observed
            source_release_time: official release timestamp (priority #1)
            ingested_at: when we fetched (priority #5 fallback)
        """
        metric = self._registry.metrics.get(field_name)
        if metric is None:
            raise ValueError(f"Unknown field_name: {field_name!r}")
        rule = self._registry.get_availability_rule(metric.availability_rule_id)

        # Priority #1: official release time
        if source_release_time is not None:
            return ResolvedAvailability(
                available_at=_to_utc(source_release_time),
                availability_type=AvailabilityType.OFFICIAL_RELEASE,
                rule_id=rule.rule_id,
                tz_aware=True,
            )

        # Priority #2 + #3: rule-driven
        resolved = self._resolve_from_rule(rule, observation_time)
        if resolved is not None:
            return resolved

        # Priority #5: fallback to ingested_at
        fallback = ingested_at or datetime.now(UTC)
        return ResolvedAvailability(
            available_at=_to_utc(fallback),
            availability_type=AvailabilityType.FETCH_TIME,
            rule_id=rule.rule_id,
            tz_aware=True,
        )

    # ----- rule resolution -----

    def _resolve_from_rule(
        self, rule: AvailabilityRule, observation_time: datetime
    ) -> ResolvedAvailability | None:
        body = rule.raw
        obs_date = observation_time.astimezone(ET).date() if observation_time.tzinfo else observation_time.date()

        # CFTC Friday release: observation = Tuesday → Friday 15:30 ET
        if "release_day_of_week" in body and "release_time_et" in body:
            release_dow = body["release_day_of_week"]
            target_dow = _dow_to_int(release_dow)
            days_ahead = (target_dow - obs_date.weekday()) % 7
            if days_ahead == 0:
                # Same day as release day but observation was earlier; should not happen
                days_ahead = 7
            candidate = obs_date + timedelta(days=days_ahead)
            if not is_trading_day(candidate):
                candidate = next_trading_day(candidate)
            hour_str = str(body["release_time_et"])
            hh, mm = (int(x) for x in hour_str.split(":")[:2])
            dt = datetime(candidate.year, candidate.month, candidate.day, hh, mm, tzinfo=ET)
            return ResolvedAvailability(
                available_at=dt,
                availability_type=AvailabilityType.RELEASE_CALENDAR,
                rule_id=rule.rule_id,
                tz_aware=True,
            )

        # FINRA T+1 14:00 ET
        if "release_hour_et" in body and "observation_to_release_lag_business_days" in body:
            n = int(body["observation_to_release_lag_business_days"])
            avail_date = add_business_days(obs_date, n)
            hour_str = str(body["release_hour_et"])
            hh, mm = (int(x) for x in hour_str.split(":")[:2])
            dt = datetime(avail_date.year, avail_date.month, avail_date.day, hh, mm, tzinfo=ET)
            return ResolvedAvailability(
                available_at=dt,
                availability_type=AvailabilityType.CONSERVATIVE_RULE,
                rule_id=rule.rule_id,
                tz_aware=True,
            )

        # FRED market proxy: T+1 18:00 ET
        if "release_hour_et" in body and "observation_to_release_lag_days" in body:
            lag = int(body["observation_to_release_lag_days"])
            avail_date = obs_date + timedelta(days=lag)
            # Calendar guard: skip to next business day
            if not is_trading_day(avail_date):
                avail_date = next_trading_day(avail_date)
            hour_str = str(body["release_hour_et"])
            hh, mm = (int(x) for x in hour_str.split(":")[:2])
            dt = datetime(avail_date.year, avail_date.month, avail_date.day, hh, mm, tzinfo=ET)
            return ResolvedAvailability(
                available_at=_to_utc(dt),
                availability_type=AvailabilityType.CONSERVATIVE_RULE,
                rule_id=rule.rule_id,
                tz_aware=True,
            )

        # yfinance close: T-day 18:00 ET (offset 2h)
        if "available_at_offset_hours" in body:
            offset = int(body["available_at_offset_hours"])
            if "observation_time_et" in body:
                hour_str = str(body["observation_time_et"])
                hh, mm = (int(x) for x in hour_str.split(":")[:2])
                obs_et = datetime(obs_date.year, obs_date.month, obs_date.day, hh, mm, tzinfo=ET)
            else:
                obs_et = observation_time.astimezone(ET)
            dt = obs_et + timedelta(hours=offset)
            return ResolvedAvailability(
                available_at=_to_utc(dt),
                availability_type=AvailabilityType.CONSERVATIVE_RULE,
                rule_id=rule.rule_id,
                tz_aware=True,
            )

        return None


def _dow_to_int(dow: str) -> int:
    return {
        "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3,
        "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6,
    }[dow.upper()]


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
