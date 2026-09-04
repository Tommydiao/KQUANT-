from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable

from .universe_catalog import InstrumentDefinition, configured_instruments


BACKFILL_PLAN_VERSION = "crypto_research_backfill_v1.0.0"


@dataclass(frozen=True)
class ResearchBackfillJob:
    symbol: str
    market_type: str
    interval: str
    start_month: str
    end_month: str
    dataset_role: str
    kind: str = "kline"

    def to_mapping(self) -> dict[str, str]:
        return asdict(self)


def _month_start(value: datetime | date) -> date:
    return date(value.year, value.month, 1)


def _shift_month(value: date, offset: int) -> date:
    total = value.year * 12 + value.month - 1 + offset
    return date(total // 12, total % 12 + 1, 1)


def _listed_month(instrument: InstrumentDefinition, floor: date) -> date:
    if not instrument.listed_since:
        return floor
    listed = datetime.fromisoformat(instrument.listed_since.replace("Z", "+00:00"))
    return max(floor, _month_start(listed))


def build_research_backfill_plan(
    root_dir: Path,
    *,
    now: datetime | None = None,
    instruments: Iterable[InstrumentDefinition] | None = None,
) -> tuple[ResearchBackfillJob, ...]:
    """Plan closed monthly archive imports without starting network work."""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    end_month = _shift_month(_month_start(current), -1)
    floor = date(2021, 1, 1)
    values = tuple(instruments or configured_instruments(root_dir))
    jobs: list[ResearchBackfillJob] = []
    for instrument in values:
        start_month = _listed_month(instrument, floor)
        if start_month > end_month:
            continue
        role = "candidate" if instrument.research_status == "candidate" else "research_universe"
        for interval in ("1h", "5m"):
            jobs.append(ResearchBackfillJob(
                symbol=instrument.symbol,
                market_type=instrument.market_type,
                interval=interval,
                start_month=start_month.isoformat(),
                end_month=end_month.isoformat(),
                dataset_role=role,
            ))
        if instrument.market_type == "perpetual":
            jobs.append(ResearchBackfillJob(
                symbol=instrument.symbol,
                market_type=instrument.market_type,
                interval="funding",
                start_month=start_month.isoformat(),
                end_month=end_month.isoformat(),
                dataset_role=role,
                kind="funding",
            ))

    rolling_start = _shift_month(_month_start(current), -2)
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        jobs.append(ResearchBackfillJob(
            symbol=symbol,
            market_type="spot",
            interval="1m",
            start_month=rolling_start.isoformat(),
            end_month=end_month.isoformat(),
            dataset_role="execution_rolling_window",
        ))
    return tuple(sorted(jobs, key=lambda item: (item.market_type, item.symbol, item.kind, item.interval)))


def summarize_backfill_plan(jobs: Iterable[ResearchBackfillJob]) -> dict[str, object]:
    values = tuple(jobs)
    return {
        "version": BACKFILL_PLAN_VERSION,
        "status": "planned",
        "network_started": False,
        "job_count": len(values),
        "symbols": sorted({item.symbol for item in values}),
        "markets": sorted({item.market_type for item in values}),
        "intervals": sorted({item.interval for item in values}),
        "jobs": [item.to_mapping() for item in values],
        "note": "Monthly archives cover completed months only; current-month tails use the REST backfill command.",
    }


__all__ = [
    "BACKFILL_PLAN_VERSION",
    "ResearchBackfillJob",
    "build_research_backfill_plan",
    "summarize_backfill_plan",
]
