from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd


UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
EXCHANGE_TIMEZONE = "America/New_York"
DISPLAY_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True)
class MarketClock:
    session: str
    market_date: str
    exchange_timezone: str
    display_timezone: str
    regular_open_utc: str | None
    regular_close_utc: str | None
    is_trading_day: bool
    is_early_close: bool
    calendar_source: str = "exchange_calendars:XNYS"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@lru_cache(maxsize=1)
def _calendar():
    return xcals.get_calendar("XNYS")


def _session_label(day: date) -> pd.Timestamp:
    return pd.Timestamp(day.isoformat())


def is_trading_day(day: date) -> bool:
    return bool(_calendar().is_session(_session_label(day)))


def previous_trading_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def next_trading_day(day: date) -> date:
    candidate = day + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def session_bounds_utc(day: date) -> tuple[datetime, datetime]:
    if not is_trading_day(day):
        raise ValueError(f"{day.isoformat()} is not an XNYS trading session")
    label = _session_label(day)
    market_open = _calendar().session_open(label).to_pydatetime().astimezone(UTC)
    market_close = _calendar().session_close(label).to_pydatetime().astimezone(UTC)
    return market_open, market_close


def is_early_close(day: date) -> bool:
    if not is_trading_day(day):
        return False
    _, market_close = session_bounds_utc(day)
    return market_close.astimezone(NEW_YORK).time() < time(16, 0)


def active_regular_session_start(now: datetime | None = None) -> datetime:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    local = current.astimezone(NEW_YORK)
    session_day = local.date()
    if not is_trading_day(session_day):
        session_day = previous_trading_day(session_day)
    else:
        session_open, _ = session_bounds_utc(session_day)
        if current < session_open:
            session_day = previous_trading_day(session_day)
    return session_bounds_utc(session_day)[0]


def market_clock(now: datetime | None = None) -> MarketClock:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    local = current.astimezone(NEW_YORK)
    local_day = local.date()
    if not is_trading_day(local_day):
        return MarketClock(
            session="closed",
            market_date=local_day.isoformat(),
            exchange_timezone=EXCHANGE_TIMEZONE,
            display_timezone=DISPLAY_TIMEZONE,
            regular_open_utc=None,
            regular_close_utc=None,
            is_trading_day=False,
            is_early_close=False,
        )
    market_open, market_close = session_bounds_utc(local_day)
    pre_open = datetime.combine(local_day, time(4, 0), tzinfo=NEW_YORK).astimezone(UTC)
    after_close = datetime.combine(local_day, time(20, 0), tzinfo=NEW_YORK).astimezone(UTC)
    if current < pre_open:
        session = "closed"
    elif current < market_open:
        session = "pre_market"
    elif current < market_close:
        session = "regular"
    elif current < after_close:
        session = "after_hours"
    else:
        session = "closed"
    return MarketClock(
        session=session,
        market_date=local_day.isoformat(),
        exchange_timezone=EXCHANGE_TIMEZONE,
        display_timezone=DISPLAY_TIMEZONE,
        regular_open_utc=market_open.isoformat(),
        regular_close_utc=market_close.isoformat(),
        is_trading_day=True,
        is_early_close=is_early_close(local_day),
    )
