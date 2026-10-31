"""Five-minute input continuations with their own clock, using the shared SDK owner."""
from contextlib import closing
from datetime import timedelta
import sqlite3

from . import options_one_minute as common
from .options_one_minute_recovery import RecoveryLane
from .options_data_paths import connect_store
from .market_clock import session_bounds_utc

KIND = 'OPENING_TREND_BAR_RECOVERY'


class TrendRecoveryLane(RecoveryLane):
    def __init__(self, evidence_path, recover, *, queue_path, clock=None):
        # Reuse the durable continuation format inside the small trend evidence DB.
        # No schema or financial records in the main ledger are changed.
        with closing(connect_store(queue_path, timeout=1)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''CREATE TABLE IF NOT EXISTS two_hour_jobs (
              job_id TEXT PRIMARY KEY, session TEXT NOT NULL, symbol TEXT NOT NULL,
              slot TEXT NOT NULL, queued_at TEXT NOT NULL, deadline_at TEXT NOT NULL,
              state TEXT NOT NULL, lease_owner TEXT, lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0,
              retry_at TEXT, reason TEXT, payload_json TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS trend_input_pending ON two_hour_jobs(state,retry_at,queued_at);''')
        self.risk_symbols = set()
        super().__init__(evidence_path, recover, queue_path=queue_path, clock=clock,
                         kind=KIND, owner='foundation-opening-trend-bars')

    def bar_ready(self, symbol, target, bar):
        if not super().bar_ready(symbol, target, bar):
            return False
        evidence = bar.get("sdk_evidence", {})
        # A claimed measured bound must govern recovery readiness as well as
        # canonical adoption. Unmeasured pulls remain raw evidence, not adoption.
        if evidence.get("clock_evidence", {}).get("state") == "VERIFIED_BOUND":
            from .options_minute_decisions import LOCAL_METHOD, _local_candidate
            if not _local_candidate(bar, {"method": LOCAL_METHOD}):
                return False
        try:
            requested = common.timestamp(bar["request_started_at"])
            received = common.timestamp(bar["received_at"])
            return bool(
                not bar.get("source_recheck_required")
                and evidence.get("provider_symbol")
                and evidence.get("adjustment") == "NoAdjust"
                and evidence.get("interface") in {
                    "QuoteContext.candlesticks", "QuoteContext.history_candlesticks_by_offset"}
                and target + timedelta(minutes=1) <= requested <= received)
        except (KeyError, TypeError, ValueError):
            return False

    def task(self, symbol, opened, bars, policy, scope_hash):
        opening, closing = session_bounds_utc(opened.astimezone(common.NY).date())
        if not opening <= opened < closing:
            return None
        minute = int((opened + timedelta(minutes=1) - opening).total_seconds() // 60)
        bucket = minute // 5 * 5
        until = opening + timedelta(minutes=bucket)
        now = self.clock()
        held = symbol in self.risk_symbols
        entry = bucket in (5, 10, 15, 20, 25) and now < opening + timedelta(minutes=policy['entry_window_minutes'])
        if not bucket or (not held and not entry):
            return None
        start = opening if entry else max(opening, until - timedelta(minutes=10))
        targets = [start + timedelta(minutes=i) for i in range(int((until-start).total_seconds()//60))]
        missing = []
        for target in targets:
            row = bars.get(target)
            if not self.bar_ready(symbol, target, row):
                missing.append(target.isoformat())
        if not missing:
            return None
        deadline = min(until + timedelta(seconds=policy['signal_deadline_seconds']), closing)
        if not held:
            deadline = min(deadline, opening + timedelta(minutes=policy['entry_window_minutes']))
        if now >= deadline:
            return None
        return {'kind': KIND, 'symbol': symbol, 'session': opening.astimezone(common.NY).date().isoformat(),
                'dependent_bar': (until-timedelta(minutes=1)).isoformat(), 'missing_bars': missing,
                'deadline_at': deadline.isoformat(), 'policy_hash': policy['policy_hash'], 'scope_hash': scope_hash,
                'priority': 0 if held else 1, 'purpose': 'REPORTED_POSITION' if held else 'OPENING_RESEARCH'}

    def _restore(self, day, policy, scope_hash):
        # Leases live in the journal. The owner recreates missing current bucket
        # tasks from its registered scope instead of scanning all minute history.
        return {}
