from datetime import UTC, date, datetime

from kquant.market_clock import is_early_close, is_trading_day, market_clock


def test_exchange_calendar_covers_special_closure() -> None:
    assert is_trading_day(date(2012, 10, 29)) is False
    assert is_trading_day(date(2012, 10, 30)) is False


def test_exchange_calendar_handles_early_close_and_dst() -> None:
    assert is_early_close(date(2026, 11, 27)) is True
    summer = market_clock(datetime(2026, 7, 13, 14, 0, tzinfo=UTC))
    winter = market_clock(datetime(2026, 1, 12, 15, 0, tzinfo=UTC))
    assert summer.regular_open_utc.endswith("13:30:00+00:00")
    assert winter.regular_open_utc.endswith("14:30:00+00:00")
