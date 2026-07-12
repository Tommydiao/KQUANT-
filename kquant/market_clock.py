from __future__ import annotations

from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


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

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (occurrence - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month, monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    # Anonymous Gregorian algorithm.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def nyse_holidays(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Presidents Day
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(_observed(date(year, 6, 19)))
    return holidays


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in nyse_holidays(day.year)


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


def is_early_close(day: date) -> bool:
    if not is_trading_day(day):
        return False
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    day_after_thanksgiving = thanksgiving + timedelta(days=1)
    return day in {
        day_after_thanksgiving,
        date(day.year, 7, 3),
        date(day.year, 12, 24),
    }


def session_bounds_utc(day: date) -> tuple[datetime, datetime]:
    close_hour = 13 if is_early_close(day) else 16
    market_open = datetime.combine(day, time(9, 30), tzinfo=NEW_YORK)
    market_close = datetime.combine(day, time(close_hour, 0), tzinfo=NEW_YORK)
    return market_open.astimezone(UTC), market_close.astimezone(UTC)


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
