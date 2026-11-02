"""Ephemeral immutable handoff; the existing durable journal remains authoritative."""
from dataclasses import dataclass, replace
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path

from kquant import options_one_minute as common
from prepared_minutes import freeze, PreparedMinute, PreparedDecision, PreparedSources


class GenerationChanged(ValueError):
    pass


def rows_token(rows):
    # Exact persisted bytes, including same-size edits; no reparsing or stat cache.
    digest = sha256()
    for raw, in rows:
        value = raw.encode('utf-8') if isinstance(raw, str) else raw
        digest.update(len(value).to_bytes(8, 'big'))
        digest.update(value)
    return len(rows), digest.hexdigest()


def file_token(path):
    try:
        return sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def scoped_file_token(path):
    from method_snapshot import checked
    path = Path(path).absolute()
    return checked(('generation-file', str(path)), lambda: file_token(path))


def price_fact_token(path, symbol, session, now):
    from generation_reads import read_connection
    with read_connection(path, seconds=.2) as db:
        rows = db.execute("""SELECT payload_json FROM two_hour_jobs
            WHERE session IN (?, 'PERSISTENT') AND symbol=? AND queued_at<=?
            AND slot IN ('PRICE_INSTRUMENT_FACT_V1', 'SESSION_PRICE_BINDING_V1')
            ORDER BY session,queued_at,job_id LIMIT 501""",
            (session, symbol, now.isoformat())).fetchall()
    if len(rows) > 500:
        raise GenerationChanged('PRICE_FACT_VERSION_READ_BOUND_EXCEEDED')
    return rows_token(rows)


def source_files(root, values, *, extra=(), scoped=False):
    """Capture only named local proof files, never walk directories or credentials."""
    from method_snapshot import resolve_path
    root = resolve_path(root)
    named = set()
    visited = set()
    def visit(value):
        if isinstance(value, (PreparedMinute, PreparedDecision, PreparedSources)):
            named.update(value.evidence_metadata[0])
            return
        if isinstance(value, (dict, list, tuple)):
            if id(value) in visited:
                return
            visited.add(id(value))
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {'source_path', 'acceptance_path'} and isinstance(child, str):
                    named.add(child)
                elif isinstance(child, (dict, list, tuple)):
                    visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
    visit(values)
    # A 55-minute generation repeats the same method proof many times. Resolve
    # each named file once, retaining the same real-path containment and hashing.
    # Explicit inputs are already bound by the caller. Keep their logical paths
    # so every byte check also observes alias retargeting; containment applies to
    # paths supplied by source documents below, not these explicit role/configs.
    paths = {Path(p).absolute() for p in set(extra)}
    for child in named:
        path = resolve_path(root / child)
        if path.is_relative_to(root):
            paths.add(path)
    reader = scoped_file_token if scoped else file_token
    return tuple((path, reader(path)) for path in sorted(paths))


def next_boundary(values, now, deadline):
    """A cached admission cannot cross a time when input eligibility could change."""
    boundaries = [deadline]
    visited = set()
    def visit(value):
        if isinstance(value, (PreparedMinute, PreparedDecision, PreparedSources)):
            boundaries.extend(point for point in value.evidence_metadata[1] if point > now)
            return
        if isinstance(value, (dict, list, tuple)):
            if id(value) in visited:
                return
            visited.add(id(value))
        if isinstance(value, dict):
            for name, item in value.items():
                if name in {'valid_until', 'expires_at', 'known_at', 'valid_from',
                            'received_at', 'available_at', 'reviewed_at', 'approved_at'}:
                    try:
                        point = common.timestamp(item)
                        if point > now:
                            boundaries.append(point)
                    except (ValueError, TypeError, AttributeError):
                        pass
                elif isinstance(item, (dict, list, tuple)):
                    visit(item)
            if value.get('state') == 'VERIFIED_BOUND' and value.get('checked_at'):
                try:
                    expiry = common.timestamp(value['checked_at']) + timedelta(seconds=900)
                    if expiry > now:
                        boundaries.append(expiry)
                except (ValueError, TypeError):
                    pass
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
    visit(values)
    return min(boundaries)


def method_authority(proof, root):
    """Receipt time bounds are separate from the method declaration itself."""
    if not isinstance(proof, dict) or not proof.get('acceptance_path'):
        return None
    from method_snapshot import resolve_path
    path = resolve_path(Path(root) / proof['acceptance_path'])
    if not path.is_relative_to(resolve_path(root)):
        return None
    try:
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != proof.get('acceptance_sha256'):
            return None
        return json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None


@dataclass(frozen=True)
class PreparedGeneration:
    key: tuple
    job: tuple
    decisions: tuple
    minute_inputs: tuple
    reviews: dict
    policy_pair: dict
    input_epoch: int
    minute_token: tuple
    decision_token: tuple
    fact_token: tuple
    files: tuple
    clock_epoch: str
    method_state: str
    prepared_at: object
    valid_before: object
    deadline: object
    fingerprint: str
    input_generation: int | None = None
    admission_timing: tuple = ()

    def admitted(self, lease, timing=None):
        if lease.fingerprint != self.fingerprint:
            raise GenerationChanged('ADMISSION_FINGERPRINT_CHANGED')
        metrics = tuple((name, (timing or {}).get(name)) for name in (
            'active_admission_wait_seconds', 'original_enqueue_age_at_preparation_seconds'))
        return replace(self, input_generation=lease.generation, admission_timing=metrics)

    def check(self, *, now, epoch, clock_epoch, minute_token, decision_token,
              fact_token, reviews, policy_pair, method_state, scoped=False):
        if not self.prepared_at <= now < self.valid_before:
            raise GenerationChanged('PREPARED_TIME_BOUNDARY_CHANGED')
        if epoch != self.input_epoch or clock_epoch != self.clock_epoch:
            raise GenerationChanged('INPUT_OR_CLOCK_EPOCH_CHANGED')
        if (minute_token != self.minute_token or decision_token != self.decision_token
                or fact_token != self.fact_token):
            raise GenerationChanged('DURABLE_INPUT_VERSION_CHANGED')
        review_identity = reviews.identity if isinstance(reviews, PreparedSources) else common.digest(reviews)
        if review_identity != self.reviews.identity or policy_pair != self.policy_pair:
            raise GenerationChanged('SOURCE_OR_POLICY_CHANGED')
        if method_state != self.method_state:
            raise GenerationChanged('METHOD_APPLICABILITY_CHANGED')
        reader = scoped_file_token if scoped else file_token
        for path, expected in self.files:
            if reader(path) != expected:
                raise GenerationChanged('SOURCE_BYTES_CHANGED')


def build(*, key, job, decisions, minute_inputs, reviews, policy_pair, epoch,
          minute_token, decision_token, fact_token, files, clock_epoch, method_state, now, deadline, fingerprint,
          authority=None):
    reviews = reviews if isinstance(reviews, PreparedSources) else PreparedSources(reviews)
    native = job[4].get('raw_quote', {})
    intraday = {name: native.get(name) for name in ('symbol', 'provider_status', 'currency', 'currency_evidence')}
    identity = common.digest([fingerprint, minute_token, decision_token, fact_token,
        [(str(p), value) for p, value in files], reviews.identity, clock_epoch, method_state,
        intraday, job[4].get('reference_blockers'), minute_inputs,
        [p['policy_hash'] for p in policy_pair.values()]])
    return PreparedGeneration(key=key, job=freeze(job), decisions=tuple(freeze(decisions)),
        minute_inputs=freeze(minute_inputs), reviews=freeze(reviews),
        policy_pair=freeze(policy_pair), input_epoch=epoch,
        minute_token=minute_token, decision_token=decision_token, fact_token=fact_token, files=files,
        clock_epoch=clock_epoch, method_state=method_state, prepared_at=now,
        valid_before=next_boundary((job[2], job[4], decisions, reviews, authority), now, deadline),
        deadline=deadline, fingerprint=identity)
