"""Bounded read-only history pages, separate from the current eligibility view."""
import json
import sqlite3
from contextlib import closing
from datetime import date
from time import monotonic

from .options_opening_trend_store import STORE
from .options_opening_trend_summary import compact_record


def history_page(*, session, policy_hash, scope_hash, before=None, limit=10, path=STORE):
    date.fromisoformat(session)
    if not policy_hash or not scope_hash or not 1 <= limit <= 50 or (before is not None and before < 1):
        raise ValueError("INVALID_HISTORY_PAGE")
    if not path.is_file():
        raise FileNotFoundError("TREND_HISTORY_UNAVAILABLE")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.2)) as c:
        deadline = monotonic() + .5
        c.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
        c.execute("BEGIN")
        # A descending immutable rowid cursor excludes new appends on later pages.
        rows = c.execute("""SELECT rowid,payload_json FROM evaluations
            WHERE policy_hash=? AND session=? AND (? IS NULL OR rowid<?)
              AND json_extract(payload_json,'$.scope_hash')=?
            ORDER BY rowid DESC LIMIT ?""",
            (policy_hash, session, before, before, scope_hash, limit + 1)).fetchall()
        items = []
        for rowid, raw in rows[:limit]:
            if monotonic() > deadline:
                raise TimeoutError("HISTORY_READ_DEADLINE")
            item = compact_record(json.loads(raw))
            # History is an original judgment, never a current actionable signal.
            item["history_only"] = True
            items.append(item)
        return {"session": session, "policy_hash": policy_hash, "scope_hash": scope_hash,
                "items": items, "next_before": rows[limit - 1][0] if len(rows) > limit else None,
                "order": "PERSISTED_DESC", "current_eligibility_included": False}
