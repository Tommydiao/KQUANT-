"""Read legacy evaluation metadata once; decode only rows used by its status view."""
from collections import Counter
from datetime import date
import json


def validate_history_sessions(values, *, session, count):
    if (not isinstance(values, list) or len(values) != count
            or any(not isinstance(value, str) for value in values)
            or values != sorted(set(values))):
        raise ValueError("STATUS_HISTORY_CONTEXT_INVALID")
    for value in values:
        if date.fromisoformat(value).isoformat() != value or value >= session:
            raise ValueError("STATUS_HISTORY_CONTEXT_INVALID")
    return values


def evaluation_view(connection, *, session, policy_hash, scope_hash):
    latest = {}
    recent = {}
    counts = Counter()
    last_bar = last_created = None
    bar_versions = {}
    # The declared metadata index covers these columns without reading JSON pages.
    for row in connection.execute("""SELECT rowid,symbol,right_name,bar_end,state,created_at
            FROM one_minute_evaluations WHERE session=?""", (session,)):
        rowid, symbol, right, bar_end, state, created = row
        key, revision = (symbol, right), (created, rowid)
        if key not in latest or revision > latest[key]:
            latest[key] = revision
        if last_created is None or created > last_created:
            last_created = created
        if last_bar is None or bar_end > last_bar:
            last_bar, bar_versions = bar_end, {key: [revision]}
        elif bar_end == last_bar:
            bar_versions.setdefault(key, []).append(revision)
        counts[state] += 1
        if state in {"NUMERIC_PASS_EVENT_PENDING", "NUMERIC_PASS"}:
            observation = (symbol, right, bar_end)
            if observation not in recent or revision > recent[observation]:
                recent[observation] = revision

    # Match the old partition order when observation timestamps tie.
    recent_ids = [revision[1] for _, revision in sorted(
        sorted(recent.items()), key=lambda item: item[1][0], reverse=True)[:20]]
    payloads = {}
    at_bar = {}

    def fetch(ids):
        wanted = sorted(set(ids)-payloads.keys())
        for offset in range(0, len(wanted), 500):
            group = wanted[offset:offset+500]
            marks = ','.join('?' for _ in group)
            for rowid, raw in connection.execute(f'''SELECT rowid,payload_json
                    FROM one_minute_evaluations WHERE rowid IN ({marks})''', group):
                payloads[rowid] = json.loads(raw)

    # Decode newest revisions first. Older policy/scope matches remain eligible,
    # but superseded rows do not all need decoding for a current summary.
    pending = {key: sorted(versions) for key, versions in bar_versions.items()}
    fetch({value[1] for value in latest.values()} | set(recent_ids)
          | {values[-1][1] for values in pending.values()})
    while pending:
        selected = {key: versions.pop() for key, versions in pending.items()}
        fetch(revision[1] for revision in selected.values())
        for key, revision in selected.items():
            payload = payloads[revision[1]]
            if (payload.get('policy_hash') == policy_hash
                    and (scope_hash is None or payload.get('scope_hash') == scope_hash)):
                at_bar[key] = revision
                del pending[key]
            elif not pending[key]:
                del pending[key]
    return {
        "rows": [payloads[revision[1]] for _, revision in sorted(latest.items())],
        "bar_rows": [payloads[revision[1]] for _, revision in sorted(at_bar.items())],
        "counts": dict(counts), "last_bar_end": last_bar, "last_evaluation_at": last_created,
        "recent_observations": [dict(payloads[rowid]) for rowid in recent_ids],
    }
