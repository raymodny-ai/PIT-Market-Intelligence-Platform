"""NYSE/Nasdaq trading calendar wrapper.

Phase 0 deliverable (TODO T-03b). All PIT paths must consult this calendar
before computing `available_at` — non-trading day handling is the most
common source of silent forward-look bias in finance.

Uses the `exchange_calendars` library which provides:
- Pre-computed holiday / early-close schedule for major exchanges
- DST-safe timezone handling
- API compatible with the official `trading_calendars` package
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache

import exchange_calendars as ecals
import pandas as pd

# Default exchange: NYSE (covers NYSE, NYSE Arca, Nasdaq via shared calendar)
DEFAULT_CALENDAR = "XNYS"


@lru_cache(maxsize=4)
def _get_calendar(name: str = DEFAULT_CALENDAR) -> ecals.ExchangeCalendar:
    """Lazy-load and cache an exchange calendar.

    Loading the full calendar is ~1-2s on cold start; lru_cache keeps it warm.
    """
    if name not in ecals.get_calendar_names():
        raise ValueError(
            f"Unknown exchange calendar: {name!r}. "
            f"Available: {sorted(ecals.get_calendar_names())}"
        )
    return ecals.get_calendar(name)


# =============================================================================
# Public API
# =============================================================================


def is_trading_day(d: date | datetime | str, calendar: str = DEFAULT_CALENDAR) -> bool:
    """Return True if `d` is a trading session (open) for `calendar`.

    Accepts ``date``, ``datetime``, or ISO-format string. Time-of-day is ignored
    for date objects; for datetime objects the date portion is used.
    """
    target = _to_date(d)
    cal = _get_calendar(calendar)
    return cal.is_session(target)


def _nearest_session_before(
    target: pd.Timestamp, cal: ecals.ExchangeCalendar
) -> date:
    """Return the most recent session strictly before `target` (any input)."""
    # sessions is a pd.DatetimeIndex; we want max < target
    sessions = cal.sessions
    if len(sessions) == 0:
        raise ValueError("Calendar has no sessions")
    if target <= sessions[0]:
        raise ValueError(f"target {target.date()} is at or before first session {sessions[0].date()}")
    idx = sessions.searchsorted(target, side="left") - 1
    if idx < 0:
        raise ValueError(f"target {target.date()} is at or before first session {sessions[0].date()}")
    return sessions[idx].date()


def _nearest_session_after(
    target: pd.Timestamp, cal: ecals.ExchangeCalendar
) -> date:
    """Return the next session strictly after `target` (any input)."""
    sessions = cal.sessions
    if len(sessions) == 0:
        raise ValueError("Calendar has no sessions")
    if target >= sessions[-1]:
        raise ValueError(f"target {target.date()} is at or after last session {sessions[-1].date()}")
    idx = sessions.searchsorted(target, side="right")
    if idx >= len(sessions):
        raise ValueError(f"target {target.date()} is at or after last session {sessions[-1].date()}")
    return sessions[idx].date()


def previous_trading_day(
    d: date | datetime | str, calendar: str = DEFAULT_CALENDAR
) -> date:
    """Return the most recent trading day strictly before `d`.

    Example: previous_trading_day(Saturday) -> Friday; previous_trading_day(Monday) -> Friday.
    """
    target = _to_date(d)
    cal = _get_calendar(calendar)
    return _nearest_session_before(target, cal)


def next_trading_day(
    d: date | datetime | str, calendar: str = DEFAULT_CALENDAR
) -> date:
    """Return the next trading day strictly after `d`.

    Example: next_trading_day(Saturday) -> Monday; next_trading_day(Friday) -> Monday.
    """
    target = _to_date(d)
    cal = _get_calendar(calendar)
    return _nearest_session_after(target, cal)


def trading_days_between(
    start: date | datetime | str,
    end: date | datetime | str,
    calendar: str = DEFAULT_CALENDAR,
) -> list[date]:
    """Return all trading days in ``[start, end]`` (inclusive both ends).

    The returned list is sorted ascending. If start > end, returns [].
    """
    s = _to_date(start)
    e = _to_date(end)
    if s > e:
        return []
    cal = _get_calendar(calendar)
    sessions = cal.sessions_in_range(s, e)
    return [pd.Timestamp(t).date() for t in sessions]


def trading_day_offset(
    d: date | datetime | str,
    n: int,
    calendar: str = DEFAULT_CALENDAR,
) -> date:
    """Shift `d` by ``n`` trading days. Positive n moves forward, negative backward.

    n=0 returns the trading day on or before `d` (i.e. rolls weekend and
    holidays back to the last open session, but if `d` is itself a trading
    day, returns `d`).

    Semantics:
    - If `d` is a trading day, `add_business_days(d, 1)` = the next trading day.
    - If `d` is not a trading day, `add_business_days(d, 1)` = the first trading
      day after `d` (i.e. the n offset is applied from the start of the next
      session).
    """
    target = _to_date(d)
    cal = _get_calendar(calendar)
    sessions = cal.sessions

    is_session = cal.is_session(target)
    if is_session:
        # target itself is a session; sessions.searchsorted with side='right' returns
        # one past the index, so subtract 1 to get the position of target.
        target_idx = sessions.searchsorted(target, side="right") - 1
    else:
        # target is not a session; we want the first session > target, which is at
        # position sessions.searchsorted(target, side='left').
        target_idx = sessions.searchsorted(target, side="left")

    if n == 0:
        if is_session:
            return target.date()
        # Return last session < target
        return sessions[target_idx - 1].date()

    new_idx = target_idx + n
    if new_idx < 0:
        raise ValueError(
            f"offset {n} from {target.date()} would go before first session {sessions[0].date()}"
        )
    if new_idx >= len(sessions):
        raise ValueError(
            f"offset {n} from {target.date()} would go after last session {sessions[-1].date()}"
        )
    return sessions[new_idx].date()


def add_business_days(
    d: date | datetime | str,
    n: int,
    calendar: str = DEFAULT_CALENDAR,
) -> date:
    """Add `n` business days to `d`, using the exchange's holiday calendar.

    This is the FUNCTION TO USE for `observation_date + 1 business day` style
    release-date math (e.g. FINRA Reg SHO T+1).
    """
    return trading_day_offset(d, n, calendar)


def is_early_close(d: date | datetime | str, calendar: str = DEFAULT_CALENDAR) -> bool:
    """Return True if `d` is an early-close trading day (e.g. Black Friday, day before Independence Day)."""
    target = _to_date(d)
    cal = _get_calendar(calendar)
    if not cal.is_session(target):
        return False
    # exchange_calendars exposes close times; early close if close < 16:00 ET (regular)
    try:
        close_time = cal.session_close(target)
        if hasattr(close_time, "time"):
            return close_time.time() < pd.Timestamp("16:00").time()
    except (NotImplementedError, AttributeError):
        return False
    return False


def holidays_in_range(
    start: date | datetime | str,
    end: date | datetime | str,
    calendar: str = DEFAULT_CALENDAR,
) -> list[date]:
    """Return list of non-trading weekdays in ``[start, end]``.

    Useful for debugging release-date calculations (e.g. confirming CFTC
    COT Friday release shifts when Friday is a holiday).
    """
    s = _to_date(start)
    e = _to_date(end)
    cal = _get_calendar(calendar)
    out: list[date] = []
    cur = s
    while cur <= e:
        # weekday check (Mon=0..Sun=6) — only weekdays can be trading days
        if cur.weekday() < 5 and not cal.is_session(cur):
            out.append(cur.date())
        cur = cur + timedelta(days=1)
    return out


# =============================================================================
# Helpers
# =============================================================================


def _to_date(d: date | datetime | str) -> pd.Timestamp:
    """Normalize input to a pandas Timestamp (date resolution)."""
    if isinstance(d, str):
        ts = pd.Timestamp(d)
    elif isinstance(d, datetime):
        ts = pd.Timestamp(d.date())
    elif isinstance(d, date):
        ts = pd.Timestamp(d)
    else:
        raise TypeError(f"Cannot convert {type(d).__name__} to date: {d!r}")
    return ts.normalize()


def calendar_version(calendar: str = DEFAULT_CALENDAR) -> str:
    """Return the version string of the underlying exchange calendar (for audit)."""
    return _get_calendar(calendar).version
