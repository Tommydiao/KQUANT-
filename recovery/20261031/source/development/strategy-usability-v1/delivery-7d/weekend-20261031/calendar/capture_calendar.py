"""Generate a read-only DST readiness artifact using installed project functions."""
from datetime import UTC, date, datetime
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
DELIVERY = HERE.parents[1]
WORKSPACE = DELIVERY.parents[1] / "workspace"
sys.path[:0] = [str(WORKSPACE), str(DELIVERY / "opening-first-hour")]
from window_calendar import budget_date, manual_exit, window


def main():
    denominator = json.loads((DELIVERY / "denominator.json").read_text(encoding="utf-8-sig"))
    policy_path = WORKSPACE / "config/options_opening_momentum_v1.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    next_day = date(2026, 11, 2)
    from zoneinfo import ZoneInfo
    from kquant import market_clock
    import first_hour
    from kquant import options_opening_trend
    paths = [Path(market_clock.__file__), Path(first_hour.__file__),
             Path(options_opening_trend.__file__), policy_path,
             DELIVERY / "denominator.json", HERE / "window_calendar.py", HERE / "test_window_calendar.py"]
    result = {
        "schema": "WEEKEND_C_CALENDAR_VERIFICATION_V1", "captured_at": datetime.now(UTC).isoformat(),
        "installed_dependencies": {name: version(name) for name in ("exchange_calendars", "pandas", "tzdata")},
        "source_hashes": {str(path): sha256(path.read_bytes()).hexdigest() for path in paths},
        "next_window": window(next_day, denominator),
        "comparison_windows": [window(day, denominator) for day in (
            date(2026, 3, 6), date(2026, 3, 9), date(2026, 10, 30), date(2026, 11, 1), date(2026, 11, 27))],
        "manual_exit_example": manual_exit(next_day, datetime(2026, 11, 2, 9, 35, tzinfo=ZoneInfo("America/New_York")), policy),
        "manual_policy_boundary": "Existing fixed BJT 01:30/01:15 preserved; this is timing verification, not S1 manual-policy approval.",
        "budget_fall_back_dates": [budget_date(datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=fold)) for fold in (0, 1)],
        "budget_boundary_scope": "Calendar contract only. Does not replace A's actual ledger/reservation acceptance.",
        "actual_schedule_registration": False, "production_tasks_created": False, "production_database_access": False,
        "market_execution_state": "NOT_RUN", "natural_signal_claim": False,
        "official_sources_checked_20261031": [
            {"url": "https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst",
             "fact": "2026 US DST begins March 8 and ends November 1; repeated local hour must not be treated as a new budget day."},
            {"url": "https://www.nyse.com/markets/hours-calendars",
             "fact": "NYSE core session is 09:30-16:00 ET; November 27 2026 is an early-close date. November 2 is not a listed holiday."}],
    }
    destination = HERE.parent / "C-evidence/calendar-verification.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(destination), "next_window": result["next_window"],
                      "manual_exit_example": result["manual_exit_example"]}, indent=2))


if __name__ == "__main__":
    main()
